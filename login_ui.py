"""
login_ui.py
ログイン状態の確認・ログインフォームの表示を担うUI部品

各ページの先頭で require_login() を呼ぶだけで
セッション管理が完結する。
"""

from __future__ import annotations
import streamlit as st
from tachibana_api import (
    login, logout, get_session, save_session, clear_session, TachibanaSession
)


def require_login() -> TachibanaSession | None:
    """
    セッションが有効なら TachibanaSession を返す。
    無効・未ログインならログインフォームを表示してNoneを返す。

    使い方:
        sess = require_login()
        if sess is None:
            st.stop()
    """
    sess = get_session()
    if sess is not None:
        _show_login_status(sess)
        return sess

    _show_login_form()
    return None


def _show_login_status(sess: TachibanaSession) -> None:
    """サイドバーにログイン状態を表示"""
    with st.sidebar:
        st.success(f"✅ ログイン中")
        st.caption(f"ログイン時刻: {sess.login_time.strftime('%H:%M:%S')}")
        if st.button("ログアウト", key="_logout_btn"):
            logout(sess)
            clear_session()
            st.rerun()


def _show_login_form() -> None:
    """ログインフォームを表示する"""
    st.warning("⚠️ ログインが必要です")

    with st.form("login_form"):
        st.markdown("### 🔐 立花証券e支店 ログイン")
        st.caption("認証情報はSecretsから自動読み込みします。ボタンを押してください。")

        submitted = st.form_submit_button("ログイン", type="primary", use_container_width=True)

    if submitted:
        try:
            user_id  = st.secrets["TACHIBANA_USER_ID"].strip()
            password = st.secrets["TACHIBANA_PASSWORD"].strip()
            base_url = st.secrets["TACHIBANA_BASE_URL"].strip()
        except KeyError as e:
            st.error(f"❌ Secretsに {e} が設定されていません")
            return

        with st.spinner("ログイン中..."):
            sess, err = login(user_id, password, base_url)

        if sess is None:
            st.error(f"❌ ログイン失敗: {err}")
            return

        save_session(sess)
        st.success("✅ ログイン成功！")
        st.rerun()
