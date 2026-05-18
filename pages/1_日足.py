"""
1_日足.py
立花証券API版 日足チャートページ
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from chart_utils import (
    setup_japanese_font, codes_input_ui,
    build_figure_6, fig_to_png, render_charts,
    DEFAULT_CODES_18, last_business_days,
)
from tachibana_api import _now_str, _post_raw
from login_ui import require_login

plt.rcParams["font.family"] = setup_japanese_font()
JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="日足", page_icon="🗓", layout="wide")
st.title("🗓 日足チャート（立花証券）")
st.caption("過去約60日の日足 | MA10/MA20/MA60・VWAP・20日高安値・RSI(14) | データ: 立花証券e支店API")

# ── ログイン確認 ──────────────────────────────────────────────
sess = require_login()
if sess is None:
    st.stop()

# ── 銘柄入力 ──────────────────────────────────────────────────
codes = codes_input_ui("codes_tachibana_daily", DEFAULT_CODES_18)

# ── 基準日選択 ────────────────────────────────────────────────
biz = last_business_days(25)
date_opts = {
    d + f" ({datetime.strptime(d,'%Y-%m-%d').strftime('%a')})" : d
    for d in biz
}
col_a, col_b = st.columns(2)
with col_a:
    sel       = st.selectbox("基準日（その日までの60日分を表示）",
                              list(date_opts.keys()), key="tb_daily_date")
    base_date = date_opts[sel]
with col_b:
    st.info(f"基準日: **{base_date}**　|　直近60営業日分を表示")


def _fetch_daily(sess, code: str) -> pd.DataFrame | None:
    """セッション経由で日足DataFrameを返す（キャッシュなし）"""
    try:
        body = sess.price({
            "sCLMID":     "CLMMfdsGetMarketPriceHistory",
            "sIssueCode": str(code).strip(),
            "sSizyouC":   "00",
        })
    except Exception as e:
        st.warning(f"{code}: 通信エラー {e}")
        return None

    if body.get("p_errno", "-1") != "0":
        st.warning(f"{code}: APIエラー {body.get('p_err', '')}")
        return None

    records = body.get("aCLMMfdsMarketPriceHistory", [])
    if not records:
        return None

    rows = []
    for rec in records:
        try:
            rows.append({
                "date":   pd.to_datetime(rec["sDate"], format="%Y%m%d"),
                "open":   float(rec["pDOP"]),
                "high":   float(rec["pDHP"]),
                "low":    float(rec["pDLP"]),
                "close":  float(rec["pDPP"]),
                "volume": float(rec["pDV"]),
            })
        except (KeyError, ValueError):
            continue

    if not rows:
        return None

    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


# ── 生成ボタン ────────────────────────────────────────────────
if st.button("📊 チャートを生成", type="primary", key="tb_daily_btn"):
    if not codes:
        st.warning("銘柄コードを入力してください")
        st.stop()

    data_map: dict = {}
    base_dt = pd.to_datetime(base_date)
    prog = st.progress(0, text="日足データ取得中...")

    for i, code in enumerate(codes):
        df_raw = _fetch_daily(sess, code)

        if df_raw is not None and len(df_raw) > 0:
            df_filtered = df_raw[df_raw["date"] <= base_dt].tail(80).copy()
            if len(df_filtered) > 0:
                # chart_utilsが期待するDateTime列を作成
                df_filtered["DateTime"] = pd.to_datetime(df_filtered["date"])
                # 列名はそのまま（open/high/low/close/volume）
                data_map[code] = df_filtered.sort_values("DateTime").reset_index(drop=True)
            else:
                data_map[code] = None
        else:
            data_map[code] = None

        prog.progress((i + 1) / len(codes), text=f"{code} 完了 ({i+1}/{len(codes)})")

    prog.empty()

    # チャート生成
    groups6 = [codes[i:i+6] for i in range(0, len(codes), 6)]
    figures  = []
    prog2 = st.progress(0, text="チャート生成中...")

    for gi, group6 in enumerate(groups6):
        fig = build_figure_6(group6, data_map, mode="daily", date_label=base_date)
        png = fig_to_png(fig)
        plt.close(fig)
        fname = f"daily_tachibana_g{gi+1}_{base_date}.png"
        figures.append((fname, png, group6))
        prog2.progress((gi+1)/len(groups6), text=f"グループ{gi+1}/{len(groups6)} 完了")

    prog2.empty()
    st.success(f"✅ {len(figures)}枚生成完了！　{datetime.now(JST).strftime('%H:%M:%S')}")
    render_charts(figures)
