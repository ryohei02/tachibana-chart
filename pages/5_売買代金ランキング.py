"""
5_売買代金ランキング.py
立花証券API版 場中リアルタイム売買代金ランキング
時価総額上位約240銘柄を対象に売買代金順にランキング表示

【修正履歴】
- 5桁変換を廃止: 4桁コードをそのまま送信（285A以外も正常取得できるよう）
- pDJ単位バグ修正: pDJは円単位のため /1e8 は正しい。ただし推計値(price*volume)も円単位で統一
- sTargetColumnを明示指定: 必要フィールドを確実に取得
- デバッグexpanderを常時表示→折りたたみ＋全バッチ確認に改善
- 自動更新ロジックを st.rerun() + session_state で正しく実装
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import matplotlib.pyplot as plt
import time
from datetime import datetime, timezone, timedelta

from chart_utils import setup_japanese_font
from login_ui import require_login

plt.rcParams["font.family"] = setup_japanese_font()
JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="売買代金ランキング", page_icon="🏆", layout="wide")
st.title("🏆 売買代金ランキング（場中リアルタイム）")
st.caption("時価総額上位約240銘柄を対象 | 立花証券e支店APIでリアルタイム取得")

# ── ログイン確認 ──────────────────────────────────────────────
sess = require_login()
if sess is None:
    st.stop()

# ── 対象銘柄リスト（時価総額上位約240銘柄・4桁コード） ──────
TARGET_CODES = [
    # 超大型（時価総額1兆円超）
    "7203","8306","9984","6861","8316","7974","6758","9432","4063","6098",
    "8411","9433","8035","6367","7267","6902","4661","9022","8766","8801",
    "6954","3382","4519","2914","6501","8802","6752","6702","9020","8058",
    "7751","7011","8031","5108","8309","2502","9021","2503","7733","9434",
    "6503","8830","6723","6971","7270","8604","4507","8591","4183","6857",
    # 大型
    "7201","5411","6645","8053","7269","7182","9101","9104","4543","6594",
    "9062","6762","4568","9107","6301","7733","5401","6273","6479","8697",
    "7735","6326","4452","2802","2282","9005","4578","7912","5713","4151",
    "6471","7832","7272","7013","3407","4911","6302","6361","4021","8015",
    "9983","1925","6967","7741","5801","3086","5803","6175","4324","6724",
    "4704","6869","4901","8750","1570","3659","8267","3099","2413","8630",
    "6963","4528","6506","4523","7186","5020","7912","3861","4005","5019",
    "6841","6770","7762","4042","5706","2768","7003","3289","4188","9064",
    "8355","9613","4689","2651","3407","9502","9531","4578","1928","3197",
    # 中型（売買代金上位に入りやすい）
    "7261","6460","4385","3092","2371","3659","6920","6146","6857","285A",
    "4755","3141","7816","2269","9843","2875","3401","6753","7731","4324",
    "6981","5105","3391","7186","4503","6976","4927","8591","3668","2587",
    "9984","4004","6988","3765","7011","6113","8252","3048","7270","2491",
    "4385","6622","7832","6268","3436","4519","6762","4021","3197","8750",
    "7203","6501","8316","6902","4063","8306","6861","8035","9432","6758",
    "9433","4661","7974","6367","8411","9022","8766","8801","6954","3382",
    "2914","8802","6752","6702","9020","8058","7751","8031","5108","8309",
]
# 重複除去・順序保持
seen = set()
CODES = []
for c in TARGET_CODES:
    if c not in seen:
        seen.add(c)
        CODES.append(c)

# ── 設定UI ────────────────────────────────────────────────────
st.info(f"対象銘柄数: **{len(CODES)}銘柄** | 表示更新: {datetime.now(JST).strftime('%H:%M:%S')}")

top_n = st.slider("表示件数", min_value=10, max_value=60, value=30, step=5)

col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    generate = st.button("🔄 取得・更新", type="primary", use_container_width=True)
with col_btn2:
    auto_refresh = st.checkbox("⏱ 60秒ごとに自動更新", value=False)

# デバッグモード切り替え
debug_mode = st.sidebar.checkbox("🔍 デバッグモード（APIレスポンス確認）", value=False)


# ══════════════════════════════════════════════════════════════
#  データ取得関数
# ══════════════════════════════════════════════════════════════

def fetch_ranking(sess, debug: bool = False) -> pd.DataFrame | None:
    """
    全対象銘柄の現在値・出来高・売買代金を取得してDataFrameを返す。

    修正ポイント:
    1. コードは4桁のままAPIに送る（5桁変換しない）
       → 以前は7203→72030に変換していたが、これが原因で285A以外が空になっていた可能性
    2. sTargetColumnを明示指定して必要フィールドを確実に取得
    3. pDJの単位: 円単位として /1e8 で億円に変換（正しい）
       → 推計値(price*volume)も円単位なので統一
    """
    all_rows = []
    batch_size = 50  # 安全のため50件ずつ（120→50に縮小）
    debug_shown = False  # デバッグ情報は最初のバッチのみ表示

    for i in range(0, len(CODES), batch_size):
        batch = CODES[i:i + batch_size]

        # ★修正1: 4桁コードをそのまま送る（5桁変換なし）
        # 285Aのような英字コードも含めてそのまま渡す
        body = sess.price({
            "sCLMID":           "CLMMfdsGetMarketPrice",
            "sTargetIssueCode": ",".join(batch),
            # ★修正2: 必要フィールドを明示指定
            # pDPP=現在値, tDPP:T=時刻, pPRP=前日終値,
            # pDYWP=騰落額, pDYRP=騰落率, pDV=出来高,
            # pDHP=高値, pDLP=安値, pDOP=始値, pDJ=売買代金
            "sTargetColumn": "pDPP,tDPP:T,pPRP,pDYWP,pDYRP,pDV,pDHP,pDLP,pDOP,pDJ",
        })

        # APIエラー時はスキップ（バッチ単位で継続）
        if body.get("p_errno", "-1") != "0":
            if debug:
                st.warning(f"バッチ{i//batch_size+1} エラー: p_errno={body.get('p_errno')} / {body.get('p_err')}")
            continue

        items = body.get("aCLMMfdsMarketPrice", [])

        # デバッグ: 最初のバッチのみ詳細表示
        if debug and not debug_shown and items:
            debug_shown = True
            with st.expander(f"🔍 APIレスポンス確認（バッチ1: {batch[:3]}... 先頭2件）", expanded=True):
                st.write(f"送信コード例（変換なし）: {batch[:5]}")
                st.write(f"取得件数: {len(items)}件 / 送信件数: {len(batch)}件")
                for _item in items[:2]:
                    st.json(_item)
                # pDJの値を確認
                if items:
                    pdj_val = items[0].get("pDJ", "（キーなし）")
                    pdp_val = items[0].get("pDPP", 0)
                    pdv_val = items[0].get("pDV", 0)
                    st.write(f"**pDJ（売買代金）**: `{pdj_val}`")
                    st.write(f"**参考**: 現在値({pdp_val}) × 出来高({pdv_val}) = {float(pdp_val or 0) * float(pdv_val or 0):,.0f}円")
                    st.caption("↑ pDJと参考値がほぼ一致→円単位、1/100程度→億円単位")

        for item in items:
            try:
                code_raw = item.get("sIssueCode", "")
                # レスポンスのコードが5桁数字なら4桁に戻す（285A等はそのまま）
                if len(code_raw) == 5 and code_raw.endswith("0") and code_raw[:-1].isdigit():
                    code = code_raw[:-1]
                else:
                    code = code_raw

                price  = float(item.get("pDPP",  0) or 0)   # 現在値
                volume = float(item.get("pDV",   0) or 0)   # 出来高
                pdj    = float(item.get("pDJ",   0) or 0)   # 売買代金（円単位）
                chg_r  = float(item.get("pDYRP", 0) or 0)   # 騰落率(%)
                chg_w  = float(item.get("pDYWP", 0) or 0)   # 騰落額
                high   = float(item.get("pDHP",  0) or 0)   # 高値
                low    = float(item.get("pDLP",  0) or 0)   # 安値
                open_  = float(item.get("pDOP",  0) or 0)   # 始値
                prev   = float(item.get("pPRP",  0) or 0)   # 前日終値
                time_  = item.get("tDPP:T", "")

                # 現在値がない場合は前日終値で代替
                if price == 0 and prev > 0:
                    price = prev

                # ★修正3: 売買代金の単位統一
                # pDJが取れていればそれを使う（円単位 → /1e8 で億円）
                # 取れていなければ 現在値×出来高 で推計（同じく円単位）
                if pdj > 0:
                    value_oku = pdj / 1e8
                elif price > 0 and volume > 0:
                    value_oku = price * volume / 1e8
                else:
                    value_oku = 0.0

                # 現在値あり・売買代金あり の銘柄のみ追加
                if price > 0 and value_oku > 0:
                    all_rows.append({
                        "code":        code,
                        "現在値":      price,
                        "騰落率(%)":   chg_r,
                        "騰落額":      chg_w,
                        "出来高":      volume,
                        "売買代金(億円)": value_oku,
                        "高値":        high,
                        "安値":        low,
                        "始値":        open_,
                        "前日終値":    prev,
                        "時刻":        time_,
                        "pDJ生値":     pdj,   # デバッグ用（後で確認できるよう保持）
                    })
            except (ValueError, TypeError):
                continue

        time.sleep(0.15)  # レート制限対策

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows)
    df = df[df["売買代金(億円)"] > 0]
    df = df.sort_values("売買代金(億円)", ascending=False).reset_index(drop=True)
    df.index += 1  # 1始まり
    return df


# ══════════════════════════════════════════════════════════════
#  実行・表示
# ══════════════════════════════════════════════════════════════

def display_ranking(df: pd.DataFrame, top_n: int, now_str: str, debug: bool):
    """ランキング結果を表示する"""

    df_top = df.head(top_n).copy()

    # ── テーブル表示 ──────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"### 📊 売買代金ランキング上位{top_n}（{now_str}時点）")

    display_df = df_top[["code","現在値","騰落率(%)","騰落額","売買代金(億円)","出来高","高値","安値"]].copy()
    display_df["売買代金(億円)"] = display_df["売買代金(億円)"].map(lambda x: f"{x:.1f}")
    display_df["出来高"]   = display_df["出来高"].map(lambda x: f"{int(x):,}")
    display_df["現在値"]   = display_df["現在値"].map(lambda x: f"{x:,.0f}")
    display_df["高値"]     = display_df["高値"].map(lambda x: f"{x:,.0f}")
    display_df["安値"]     = display_df["安値"].map(lambda x: f"{x:,.0f}")
    display_df["騰落額"]   = display_df["騰落額"].map(lambda x: f"{x:+.0f}")
    display_df["騰落率(%)"] = display_df["騰落率(%)"].map(lambda x: f"{x:+.2f}%")
    display_df.columns = ["コード","現在値","騰落率","騰落額","売買代金(億)","出来高","高値","安値"]

    st.dataframe(
        display_df,
        use_container_width=True,
        height=min(60 + top_n * 35, 800),
    )

    # ── pDJ生値デバッグ表示 ───────────────────────────────────
    if debug:
        with st.expander("🔍 pDJ生値確認（上位10件）"):
            debug_df = df_top.head(10)[["code","現在値","出来高","pDJ生値","売買代金(億円)"]].copy()
            debug_df["推計値(億)"] = debug_df["現在値"] * debug_df["出来高"] / 1e8
            st.dataframe(debug_df)
            st.caption("pDJ生値 ÷ 1e8 ≈ 売買代金(億円) なら円単位で正しい。大きくズレる場合は単位要確認。")

    # ── コードコピー用 ────────────────────────────────────────
    st.markdown("---")
    top18_codes = df_top.head(18)["code"].tolist()
    st.markdown("### 📋 上位18銘柄コード（チャートページ用）")
    st.code(",".join(top18_codes), language=None)

    # ── 棒グラフ ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📈 売買代金グラフ")

    fig, ax = plt.subplots(figsize=(12, max(4, top_n * 0.35)))
    colors = ["#E74C3C" if v > 0 else ("#3498DB" if v < 0 else "#888888")
              for v in df_top["騰落率(%)"]]
    bars = ax.barh(
        range(len(df_top)),
        df_top["売買代金(億円)"],
        color=colors, alpha=0.85,
    )
    ax.set_yticks(range(len(df_top)))
    ax.set_yticklabels(
        [f"{idx+1}. {row['code']}  {row['騰落率(%)']:+.2f}%"
         for idx, row in df_top.reset_index(drop=True).iterrows()],
        fontsize=9,
    )
    ax.invert_yaxis()
    ax.set_xlabel("売買代金（億円）", fontsize=10)
    ax.set_title(f"売買代金ランキング上位{top_n}　{now_str}時点", fontsize=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)

    # 値ラベル
    max_val = df_top["売買代金(億円)"].max()
    for bar, val in zip(bars, df_top["売買代金(億円)"]):
        ax.text(
            bar.get_width() + max_val * 0.005,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.0f}億",
            va="center", fontsize=8,
        )

    # 凡例
    import matplotlib.patches as mpatches
    ax.legend(
        handles=[
            mpatches.Patch(color="#E74C3C", label="上昇"),
            mpatches.Patch(color="#3498DB", label="下落"),
        ],
        loc="lower right", fontsize=9,
    )

    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


# ── メイン実行 ────────────────────────────────────────────────
if generate or (auto_refresh and "last_fetch" not in st.session_state):
    with st.spinner(f"{len(CODES)}銘柄のデータを取得中...（約5〜10秒）"):
        t0 = time.time()
        df = fetch_ranking(sess, debug=debug_mode)
        elapsed = time.time() - t0

    if df is None or df.empty:
        st.error("データを取得できませんでした。デバッグモードをONにして再試行してください。")
        st.stop()

    now_str = datetime.now(JST).strftime("%H:%M:%S")
    st.success(f"✅ {len(df)}銘柄取得完了　{now_str}　（{elapsed:.1f}秒）")

    # session_stateに保存（自動更新用）
    st.session_state["ranking_df"]    = df
    st.session_state["ranking_time"]  = now_str
    st.session_state["last_fetch"]    = time.time()

# 保存済みデータがあれば表示
if "ranking_df" in st.session_state:
    display_ranking(
        st.session_state["ranking_df"],
        top_n,
        st.session_state.get("ranking_time", ""),
        debug=debug_mode,
    )

# 自動更新: 60秒待ってrerun
if auto_refresh:
    last = st.session_state.get("last_fetch", 0)
    remaining = 60 - int(time.time() - last)
    if remaining > 0:
        st.caption(f"⏱ 次の自動更新まで {remaining} 秒")
        time.sleep(1)
        st.rerun()
    else:
        # 60秒経過→再取得
        del st.session_state["last_fetch"]
        st.rerun()
