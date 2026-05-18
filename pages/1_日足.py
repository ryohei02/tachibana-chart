"""
1_日足.py
立花証券API版 日足チャートページ
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta

from chart_utils import (
    setup_japanese_font, codes_input_ui,
    build_figure_6, fig_to_png, render_charts,
    DEFAULT_CODES_18, last_business_days,
)
from tachibana_api import (
    get_session, get_daily_history, get_issue_names_bulk, _to_4digit,
)
from login_ui import require_login

import pandas as pd
import numpy as np

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

# ── 生成ボタン ────────────────────────────────────────────────
if st.button("📊 チャートを生成", type="primary", key="tb_daily_btn"):
    if not codes:
        st.warning("銘柄コードを入力してください")
        st.stop()

    # 日足データ取得
    data_map: dict = {}
    prog = st.progress(0, text="日足データ取得中...")

    # ── デバッグ: 1銘柄目のAPIレスポンスを表示 ──
    _debug_code = codes[0] if codes else "69200"
    with st.expander(f"🔍 デバッグ情報（{_debug_code}）", expanded=True):
        import json, urllib.parse
        from tachibana_api import _to_5digit, _now_str, _next_p_no
        _params = {
            "sCLMID": "CLMMfdsGetMarketPriceHistory",
            "sIssueCode": _to_5digit(_debug_code),
            "sSizyouC": "00",
            "p_no": "99",
            "p_sd_date": _now_str(),
            "sJsonOfmt": "5",
        }
        import requests
        _r = requests.post(sess.url_price,
                          data=json.dumps(_params, ensure_ascii=False, separators=(",",":")),
                          headers={"Content-Type": "application/json"}, timeout=20)
        st.write(f"URL: `{sess.url_price}`")
        st.write(f"ステータス: {_r.status_code}")
        try:
            _body = _r.json()
            _records = _body.get("aCLMMfdsMarketPriceHistory", [])
            st.write(f"p_errno: {_body.get('p_errno')}  /  レコード件数: {len(_records)}")
            if _records:
                st.write("最新3件:", _records[-3:])
            else:
                st.json(_body)
        except:
            st.text(_r.text[:500])

    for i, code in enumerate(codes):
        with st.spinner(f"{code} 取得中..."):
            df_raw = get_daily_history(sess.url_price, code)

        if df_raw is not None and len(df_raw) > 0:
            # base_dateでフィルタリングして直近60本
            base_dt = pd.to_datetime(base_date)
            df_filtered = df_raw[df_raw["date"] <= base_dt].tail(80).copy()

            if len(df_filtered) > 0:
                # chart_utilsのplot_daily_stockが期待する列名に変換
                df_filtered = df_filtered.rename(columns={
                    "date":   "t",
                    "open":   "o",
                    "high":   "h",
                    "low":    "l",
                    "close":  "c",
                    "volume": "v",
                })
                df_filtered["t"] = pd.to_datetime(df_filtered["t"])
                data_map[code] = df_filtered
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
