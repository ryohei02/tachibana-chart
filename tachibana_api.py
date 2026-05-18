"""
tachibana_api.py
立花証券e支店API v4r9 ラッパー

役割:
  - ログイン / ログアウト / セッション管理
  - 日足データ取得 (CLMMfdsGetMarketPriceHistory)
  - 現在値スナップショット取得 (CLMMfdsGetMarketPrice)
  - 銘柄名マスタ取得 (CLMIssueMstKabu)

セッションはStreamlit session_stateにキャッシュし、
1日1回のログインで使い回す。
"""

from __future__ import annotations

import json
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
import pandas as pd
import streamlit as st

JST = timezone(timedelta(hours=9))

# ── 定数 ──────────────────────────────────────────────────────
SESSION_KEY   = "_tachibana_session"   # st.session_state キー
_TIMEOUT      = 20                     # HTTP タイムアウト秒
_P_NO_KEY     = "_tachibana_p_no"      # リクエスト連番


# ══════════════════════════════════════════════════════════════
#  内部ユーティリティ
# ══════════════════════════════════════════════════════════════

def _now_str() -> str:
    """API要求日時文字列 'YYYY.MM.DD-HH:MM:SS.mmm' を返す"""
    now = datetime.now(JST)
    return now.strftime("%Y.%m.%d-%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _next_p_no() -> str:
    """リクエスト連番を返す。常に前回+1を保証する"""
    if _P_NO_KEY not in st.session_state:
        st.session_state[_P_NO_KEY] = 1
    n = st.session_state[_P_NO_KEY]
    st.session_state[_P_NO_KEY] = n + 1
    return str(n)

def _reset_p_no() -> None:
    """ログイン時にp_noをリセットする"""
    st.session_state[_P_NO_KEY] = 1


def _build_query(params: dict) -> str:
    """dict → URLエンコードされたクエリ文字列に変換"""
    params["p_no"]     = _next_p_no()
    params["p_sd_date"] = _now_str()
    params["sJsonOfmt"] = "5"
    json_str = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    return urllib.parse.quote(json_str)


def _get(url_base: str, params: dict) -> dict:
    """
    指定URLにGETリクエストを送り、JSONレスポンスを返す。
    エラー時は {"p_errno": "-1", "p_err": "<message>"} を返す。
    """
    query   = _build_query(params)
    full_url = f"{url_base}?{query}"
    try:
        r = requests.get(full_url, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        return {"p_errno": "-1", "p_err": "タイムアウト"}
    except requests.exceptions.RequestException as e:
        return {"p_errno": "-1", "p_err": str(e)}
    except Exception as e:
        return {"p_errno": "-1", "p_err": f"予期しないエラー: {e}"}


def _post_raw(url_base: str, params: dict) -> dict:
    """POSTリクエスト（p_no等はすでにparamsに含まれている前提）"""
    try:
        r = requests.post(
            url_base,
            data=json.dumps(params, ensure_ascii=False, separators=(",", ":")),
            headers={"Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        return {"p_errno": "-1", "p_err": "タイムアウト"}
    except requests.exceptions.RequestException as e:
        return {"p_errno": "-1", "p_err": str(e)}
    except Exception as e:
        return {"p_errno": "-1", "p_err": f"予期しないエラー: {e}"}

def _post(url_base: str, params: dict) -> dict:
    """後方互換用。_post_rawに委譲"""
    return _post_raw(url_base, params)


# ══════════════════════════════════════════════════════════════
#  セッション管理
# ══════════════════════════════════════════════════════════════

class TachibanaSession:
    """ログイン後のセッション情報を保持するデータクラス"""
    def __init__(self, raw: dict, base_url: str):
        self.base_url      = base_url
        self.url_request   = raw.get("sUrlRequest", "")   # 業務系URL
        self.url_master    = raw.get("sUrlMaster",  "")   # マスタURL
        self.url_price     = raw.get("sUrlPrice",   "")   # 時価URL
        self.url_event     = raw.get("sUrlEvent",   "")   # イベントURL
        self.login_time    = datetime.now(JST)
        self._p_no         = 2  # ログインでp_no=1を使用済みなので2から開始

    def next_p_no(self) -> str:
        """セッション内のリクエスト連番を返す（常に増加）"""
        n = self._p_no
        self._p_no += 1
        return str(n)

    def is_valid(self) -> bool:
        """03:30以前かつ同日ログインならセッション有効とみなす"""
        now = datetime.now(JST)
        cutoff = now.replace(hour=3, minute=30, second=0, microsecond=0)
        if now < cutoff:
            # 日付をまたいで使う場合は無効
            return self.login_time.date() == now.date()
        return True

    def req(self, params: dict) -> dict:
        """業務系リクエスト送信"""
        params["p_no"]      = self.next_p_no()
        params["p_sd_date"] = _now_str()
        params["sJsonOfmt"] = "5"
        return _post_raw(self.url_request, params)

    def master(self, params: dict) -> dict:
        """マスタリクエスト送信"""
        params["p_no"]      = self.next_p_no()
        params["p_sd_date"] = _now_str()
        params["sJsonOfmt"] = "5"
        return _post_raw(self.url_master, params)

    def price(self, params: dict) -> dict:
        """時価リクエスト送信"""
        params["p_no"]      = self.next_p_no()
        params["p_sd_date"] = _now_str()
        params["sJsonOfmt"] = "5"
        return _post_raw(self.url_price, params)


def login(user_id: str, password: str, base_url: str) -> tuple[TachibanaSession | None, str]:
    """
    ログインを実行し TachibanaSession を返す。
    失敗時は (None, エラーメッセージ) を返す。
    """
    auth_url = base_url + "auth/"
    params = {
        "p_no":      "1",
        "p_sd_date": _now_str(),
        "sCLMID":    "CLMAuthLoginRequest",
        "sUserId":   user_id,
        "sPassword": password,
        "sJsonOfmt": "5",
    }
    resp = _post_raw(auth_url, params)

    errno = resp.get("p_errno", "-1")
    if errno != "0":
        err_msg = resp.get("p_err", "ログイン失敗")
        detail = f"p_errno={errno} / {err_msg} / auth_url={auth_url}"
        return None, detail

    session = TachibanaSession(resp, base_url)
    if not session.url_request:
        return None, "セッションURLが取得できませんでした"

    # ログイン成功時にp_noをリセット（新セッション開始）
    _reset_p_no()
    return session, ""


def logout(session: TachibanaSession) -> None:
    """ログアウトを実行する（失敗しても無視）"""
    try:
        auth_url = session.base_url + "auth/"
        params   = {"sCLMID": "CLMAuthLogoutRequest"}
        _post(auth_url, params)
    except Exception:
        pass


def get_session() -> TachibanaSession | None:
    """
    Streamlit session_stateからセッションを取得する。
    存在しないか無効な場合はNoneを返す。
    """
    sess = st.session_state.get(SESSION_KEY)
    if sess and sess.is_valid():
        return sess
    return None


def save_session(session: TachibanaSession) -> None:
    """セッションをStreamlit session_stateに保存する"""
    st.session_state[SESSION_KEY] = session


def clear_session() -> None:
    """セッションをクリアする"""
    if SESSION_KEY in st.session_state:
        del st.session_state[SESSION_KEY]


# ══════════════════════════════════════════════════════════════
#  データ取得
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def get_daily_history(
    _session_url_price: str,
    code: str,
) -> pd.DataFrame | None:
    """
    日足履歴を取得する（最大20年分）。
    キャッシュTTL: 1時間

    Args:
        _session_url_price: セッションのPRICE URL（キャッシュキーに使用）
        code: 銘柄コード（4桁または5桁）

    Returns:
        DataFrame (columns: date, open, high, low, close, volume) or None
    """
    sess = get_session()
    if sess is None:
        return None

    # コードはそのまま送る（4桁が基本、5桁は優先株等のみ）
    resp = sess.price({
        "sCLMID":     "CLMMfdsGetMarketPriceHistory",
        "sIssueCode": str(code).strip(),
        "sSizyouC":   "00",  # 東証
    })

    if resp.get("p_errno", "-1") != "0":
        return None

    records = resp.get("aCLMMfdsMarketPriceHistory", [])
    if not records:
        return None

    rows = []
    for r in records:
        try:
            rows.append({
                "date":   pd.to_datetime(r["sDate"], format="%Y%m%d"),
                "open":   float(r["pDOP"]),
                "high":   float(r["pDHP"]),
                "low":    float(r["pDLP"]),
                "close":  float(r["pDPP"]),
                "volume": float(r["pDV"]),
            })
        except (KeyError, ValueError):
            continue

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def get_snapshot(
    _session_url_price: str,
    codes: list[str],
) -> dict[str, dict]:
    """
    複数銘柄の現在値スナップショットを一括取得する。
    キャッシュTTL: 60秒

    Returns:
        {code: {open, high, low, close, volume, prev_close, change_rate, time}}
    """
    sess = get_session()
    if sess is None:
        return {}

    codes5 = [_to_5digit(c) for c in codes]
    resp = sess.price({
        "sCLMID":          "CLMMfdsGetMarketPrice",
        "sTargetIssueCode": ",".join(codes5),
        "sTargetColumn":   "pDPP,tDPP:T,pPRP,pDYWP,pDYRP,pDV,pDHP,pDLP,pDOP",
    })

    if resp.get("p_errno", "-1") != "0":
        return {}

    result = {}
    for item in resp.get("aCLMMfdsMarketPrice", []):
        code4 = _to_4digit(item.get("sIssueCode", ""))
        result[code4] = {
            "close":       _f(item.get("pDPP")),
            "time":        item.get("tDPP:T", ""),
            "prev_close":  _f(item.get("pPRP")),
            "change":      _f(item.get("pDYWP")),
            "change_rate": _f(item.get("pDYRP")),
            "volume":      _f(item.get("pDV")),
            "high":        _f(item.get("pDHP")),
            "low":         _f(item.get("pDLP")),
            "open":        _f(item.get("pDOP")),
        }
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def get_issue_name(
    _session_url_master: str,
    code: str,
) -> str:
    """
    銘柄名を取得する（1日キャッシュ）。
    取得失敗時はコードをそのまま返す。
    """
    sess = get_session()
    if sess is None:
        return code

    code5 = _to_5digit(code)
    resp = sess.master({
        "sCLMID":     "CLMIssueMstKabu",
        "sIssueCode": code5,
        "sSizyouC":   "00",
    })

    if resp.get("p_errno", "-1") != "0":
        return code

    items = resp.get("aCLMIssueMstKabu", [])
    if items:
        return items[0].get("sIssueName", code)
    return code


@st.cache_data(ttl=86400, show_spinner=False)
def get_issue_names_bulk(
    _session_url_master: str,
    codes: tuple[str, ...],
) -> dict[str, str]:
    """
    複数銘柄の銘柄名を一括取得する（1日キャッシュ）。
    Returns: {code4: name}
    """
    result = {}
    for code in codes:
        name = get_issue_name(_session_url_master, code)
        result[_to_4digit(code)] = name
        time.sleep(0.12)   # 秒10件制限対策
    return result


# ══════════════════════════════════════════════════════════════
#  コードユーティリティ
# ══════════════════════════════════════════════════════════════

def _to_5digit(code: str) -> str:
    """4桁→5桁（末尾0付加）。285Aなど英字コードはそのまま"""
    code = str(code).strip()
    if len(code) == 4 and code.isdigit():
        return code + "0"
    return code


def _to_4digit(code: str) -> str:
    """5桁→4桁（末尾0削除）。英字コードはそのまま"""
    code = str(code).strip()
    if len(code) == 5 and code.endswith("0") and code[:-1].isdigit():
        return code[:-1]
    return code


def _f(val) -> float:
    """文字列→floatに変換。失敗時は0.0"""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
