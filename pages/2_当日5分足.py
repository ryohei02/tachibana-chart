"""
2_当日5分足.py
立花証券API版 当日5分足チャートページ
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import requests
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from chart_utils import (
    setup_japanese_font, codes_input_ui,
    build_figure_6, fig_to_png, render_charts,
    DEFAULT_CODES_18, last_business_days,
)
from tachibana_api import _now_str
from login_ui import require_login

plt.rcParams["font.family"] = setup_japanese_font()
JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="当日5分足", page_icon="📊", layout="wide")
st.title("📊 当日 5分足チャート（立花証券）")
st.caption("MA10/MA20・VWAP・前日高値／安値／終値 | データ: 立花証券e支店API")

# ── ログイン確認 ──────────────────────────────────────────────
sess = require_login()
if sess is None:
    st.stop()

# ── 銘柄入力 ──────────────────────────────────────────────────
codes = codes_input_ui("codes_tachibana_intraday_5", DEFAULT_CODES_18)

# ── 設定 ──────────────────────────────────────────────────────
biz      = last_business_days(12)
today    = biz[0] if biz else datetime.now(JST).strftime("%Y-%m-%d")
prev_date = biz[1] if len(biz) > 1 else None

col_a, col_b = st.columns(2)
with col_a:
    bar_min = st.selectbox("足の種類", [5, 10, 15, 30], index=0, key="tb_5min_barmin")
with col_b:
    st.info(f"対象日: **{today}**　|　前日補完用: **{prev_date}**")


def _fetch_minute(sess, code: str, date_str: str) -> pd.DataFrame | None:
    """分足データを取得してDataFrameを返す"""
    body = sess.price({
        "sCLMID":     "CLMMfdsGetMarketPriceMinuteHistory",
        "sIssueCode": str(code).strip(),
        "sSizyouC":   "00",
        "sDate":      date_str.replace("-", ""),  # YYYYMMDD形式
    })

    if body.get("p_errno", "-1") != "0":
        return None

    records = body.get("aCLMMfdsMarketPriceMinuteHistory", [])
    if not records:
        return None

    rows = []
    for rec in records:
        try:
            # DateTime = sDate + sTime (YYYYMMDD + HHMM)
            dt_str = rec.get("sDate", "") + " " + rec.get("sTime", "")
            rows.append({
                "DateTime": pd.to_datetime(dt_str, format="%Y%m%d %H%M"),
                "open":     float(rec.get("pOP",  rec.get("pDOP",  0))),
                "high":     float(rec.get("pHP",  rec.get("pDHP",  0))),
                "low":      float(rec.get("pLP",  rec.get("pDLP",  0))),
                "close":    float(rec.get("pPP",  rec.get("pDPP",  0))),
                "volume":   float(rec.get("pV",   rec.get("pDV",   0))),
            })
        except (KeyError, ValueError):
            continue

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("DateTime").reset_index(drop=True)
    return df


# ── 生成ボタン ────────────────────────────────────────────────
if st.button("📊 チャートを生成", type="primary", key="tb_5min_btn"):
    if not codes:
        st.warning("銘柄コードを入力してください")
        st.stop()

    data_map: dict = {}
    prev_map: dict = {}
    prog = st.progress(0, text="分足データ取得中...")

    for i, code in enumerate(codes):
        # 当日分足
        df_today = _fetch_minute(sess, code, today)
        # 前日分足（MA補完用）
        df_prev = _fetch_minute(sess, code, prev_date) if prev_date else None

        if df_today is not None and len(df_today) > 0:
            # リサンプル（5分足等）
            if bar_min > 1:
                df_r = df_today.set_index("DateTime").resample(f"{bar_min}min").agg(
                    {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
                ).dropna(subset=["open","close"])
                df_r = df_r[df_r["open"] > 0].reset_index()
            else:
                df_r = df_today.copy()
            data_map[code] = df_r
        else:
            data_map[code] = None

        if df_prev is not None and len(df_prev) > 0:
            prev_map[code] = df_prev
        else:
            prev_map[code] = None

        prog.progress((i + 1) / len(codes), text=f"{code} 完了 ({i+1}/{len(codes)})")

    prog.empty()

    # デバッグ: 1銘柄目のAPIレスポンスキーを確認
    if codes:
        test_code = codes[0]
        body_test = sess.price({
            "sCLMID":     "CLMMfdsGetMarketPriceMinuteHistory",
            "sIssueCode": str(test_code).strip(),
            "sSizyouC":   "00",
            "sDate":      today.replace("-", ""),
        })
        with st.expander(f"🔍 APIレスポンス確認 ({test_code})", expanded=True):
            st.write(f"p_errno: {body_test.get('p_errno')}")
            st.write(f"p_err: {body_test.get('p_err')}")
            keys = list(body_test.keys())
            st.write(f"レスポンスキー一覧: {keys}")
            # データキーを探す
            for k in keys:
                if isinstance(body_test[k], list) and len(body_test[k]) > 0:
                    st.write(f"データキー: {k}, 件数: {len(body_test[k])}")
                    st.write("先頭1件:", body_test[k][0])
                    break

    # チャート生成
    groups6 = [codes[i:i+6] for i in range(0, len(codes), 6)]
    figures  = []
    prog2 = st.progress(0, text="チャート生成中...")

    for gi, group6 in enumerate(groups6):
        fig = build_figure_6(
            group6, data_map, mode="intraday",
            bar_min=bar_min, date_label=today
        )
        png = fig_to_png(fig)
        plt.close(fig)
        fname = f"5min_today_g{gi+1}_{today}.png"
        figures.append((fname, png, group6))
        prog2.progress((gi+1)/len(groups6), text=f"グループ{gi+1}/{len(groups6)} 完了")

    prog2.empty()
    st.success(f"✅ {len(figures)}枚生成完了！　{datetime.now(JST).strftime('%H:%M:%S')}")
    render_charts(figures)
