"""
Home.py
立花証券e支店API版 株価チャートアプリ
"""

import streamlit as st
from login_ui import require_login

st.set_page_config(page_title="株チャート（立花証券）", page_icon="📈", layout="wide")
st.title("📈 株価チャートアプリ（立花証券e支店API）")
st.markdown("---")

# ── ログイン ──────────────────────────────────────────────────
sess = require_login()
if sess is None:
    st.info("ログインすると各ページのチャートが利用できます。")
    st.stop()

st.success("✅ ログイン済み　| 左のサイドバーからページを選択してください")
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    #### 🗓 日足
    過去約60日の日足チャート
    MA10/MA20/MA60・VWAP・RSI(14)・20日高安値
    """)
    st.page_link("pages/1_日足.py", label="🗓 日足チャートへ", use_container_width=True)

    st.markdown("---")

    st.markdown("""
    #### 📊 当日5分足
    当日の5分足チャート（引け後に表示可能）
    MA10/MA20・VWAP・前日高値安値終値
    """)
    st.page_link("pages/2_当日5分足.py", label="📊 当日5分足チャートへ", use_container_width=True)

with col2:
    st.markdown("""
    #### ⚡ 当日1分足
    当日の1分足チャート（直近N本）
    MA10/MA20・VWAP・前日高値安値終値
    """)
    st.page_link("pages/3_当日1分足.py", label="⚡ 当日1分足チャートへ", use_container_width=True)

    st.markdown("---")

    st.markdown("""
    #### 📉 前日5分足
    前日の5分足チャート
    日付を選択して表示
    """)
    st.page_link("pages/4_前日5分足.py", label="📉 前日5分足チャートへ", use_container_width=True)

st.markdown("---")
st.caption("データ提供: 立花証券e支店API | J-Quantsアプリと同じ描画ロジックを使用")
