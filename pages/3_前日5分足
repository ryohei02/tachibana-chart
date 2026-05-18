"""
3_前日5分足.py
立花証券API版 前日5分足チャートページ
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timezone, timedelta

from chart_utils import (
    setup_japanese_font, codes_input_ui,
    build_figure_6, fig_to_png, render_charts,
    DEFAULT_CODES_18, last_business_days,
)
from login_ui import require_login

plt.rcParams["font.family"] = setup_japanese_font()
JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="前日5分足", page_icon="📉", layout="wide")
st.title("📉 前日 5分足チャート（立花証券）")
st.caption("MA10/MA20・VWAP・前日高値／安値／終値 | データ: 立花証券e支店API")

# ── ログイン確認 ──────────────────────────────────────────────
sess = require_login()
if sess is None:
    st.stop()

# ── 銘柄入力 ──────────────────────────────────────────────────
codes = codes_input_ui("codes_tachibana_prev5", DEFAULT_CODES_18)

# ── 設定 ──────────────────────────────────────────────────────
biz = last_business_days(25)

col_a, col_b = st.columns(2)
with col_a:
    bar_min = st.selectbox("足の種類", [5, 10, 15, 30], index=0, key="tb_prev5_barmin")
with col_b:
    date_opts = {
        d + f" ({datetime.strptime(d,'%Y-%m-%d').strftime('%a')})" : d
        for d in biz[1:]
    }
    sel = st.selectbox("対象日（前日〜約1ヶ月前）", list(date_opts.keys()), key="tb_prev5_date")
    target_date = date_opts[sel]

ti        = biz.index(target_date)
prev_date = biz[ti+1] if ti+1 < len(biz) else None
st.info(f"対象日: **{target_date}**　|　前日補完用: **{prev_date}**")


def _fetch_minute(sess, code: str, date_str: str) -> pd.DataFrame | None:
    """分足データを取得してDataFrameを返す"""
    body = sess.price({
        "sCLMID":     "CLMMfdsGetMarketPriceMinuteHistory",
        "sIssueCode": str(code).strip(),
        "sSizyouC":   "00",
        "sDate":      date_str.replace("-", ""),
    })

    if body.get("p_errno", "-1") != "0":
        return None

    # レスポンスキーを動的に探す
    records = None
    for k, v in body.items():
        if isinstance(v, list) and len(v) > 0 and "sDate" in str(v[0]):
            records = v
            break
    if not records:
        records = body.get("aCLMMfdsMarketPriceMinuteHistory", [])
    if not records:
        return None

    rows = []
    for rec in records:
        try:
            dt_str = str(rec.get("sDate", "")) + " " + str(rec.get("sTime", ""))
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

    return pd.DataFrame(rows).sort_values("DateTime").reset_index(drop=True)


# ── 生成ボタン ────────────────────────────────────────────────
if st.button("📊 チャートを生成", type="primary", key="tb_prev5_btn"):
    if not codes:
        st.warning("銘柄コードを入力してください")
        st.stop()

    data_map: dict = {}
    prog = st.progress(0, text="分足データ取得中...")

    for i, code in enumerate(codes):
        df_raw = _fetch_minute(sess, code, target_date)

        if df_raw is not None and len(df_raw) > 0:
            if bar_min > 1:
                df_r = df_raw.set_index("DateTime").resample(f"{bar_min}min").agg(
                    {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
                ).dropna(subset=["open","close"])
                df_r = df_r[df_r["open"] > 0].reset_index()
            else:
                df_r = df_raw.copy()
            data_map[code] = df_r
        else:
            data_map[code] = None

        prog.progress((i + 1) / len(codes), text=f"{code} 完了 ({i+1}/{len(codes)})")

    prog.empty()

    groups6 = [codes[i:i+6] for i in range(0, len(codes), 6)]
    figures  = []
    prog2 = st.progress(0, text="チャート生成中...")

    for gi, group6 in enumerate(groups6):
        fig = build_figure_6(
            group6, data_map, mode="intraday",
            bar_min=bar_min, date_label=target_date
        )
        png = fig_to_png(fig)
        plt.close(fig)
        fname = f"5min_prev_g{gi+1}_{target_date}.png"
        figures.append((fname, png, group6))
        prog2.progress((gi+1)/len(groups6), text=f"グループ{gi+1}/{len(groups6)} 完了")

    prog2.empty()
    st.success(f"✅ {len(figures)}枚生成完了！　{datetime.now(JST).strftime('%H:%M:%S')}")
    render_charts(figures)
