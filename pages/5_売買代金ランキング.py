"""
5_売買代金ランキング.py
立花証券API版 場中リアルタイム売買代金ランキング
時価総額上位約240銘柄を対象に売買代金順にランキング表示
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
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
# プライム市場 時価総額上位銘柄
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

# ── 設定 ──────────────────────────────────────────────────────
st.info(f"対象銘柄数: **{len(CODES)}銘柄** | 取得時刻: {datetime.now(JST).strftime('%H:%M:%S')}")

top_n = st.slider("表示件数", min_value=10, max_value=60, value=30, step=5)

col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    generate = st.button("🔄 取得・更新", type="primary", use_container_width=True)
with col_btn2:
    auto_refresh = st.checkbox("⏱ 60秒ごとに自動更新", value=False)


def fetch_ranking(sess) -> pd.DataFrame | None:
    """全対象銘柄の現在値・出来高・売買代金を取得してDataFrameを返す"""
    # 取得する情報コード
    columns = "pDPP,pDYRP,pDV,pDJ,pDHP,pDLP,pDOP,pPRP,tDPP:T"

    all_rows = []
    batch_size = 120  # 1リクエスト最大120銘柄

    for i in range(0, len(CODES), batch_size):
        batch = CODES[i:i + batch_size]
        # 4桁→5桁コードに変換（APIは5桁コードが必要な場合あり）
        batch_codes = []
        for c in batch:
            if len(c) == 4 and c.isdigit():
                batch_codes.append(c + "0")
            else:
                batch_codes.append(c)

        body = sess.price({
            "sCLMID":          "CLMMfdsGetMarketPrice",
            "sTargetIssueCode": ",".join(batch_codes),
            "sTargetColumn":   columns,
        })

        if body.get("p_errno", "-1") != "0":
            continue

        for item in body.get("aCLMMfdsMarketPrice", []):
            try:
                code_raw = item.get("sIssueCode", "")
                # 5桁→4桁変換
                code = code_raw[:-1] if (len(code_raw) == 5 and code_raw.endswith("0") and code_raw[:-1].isdigit()) else code_raw

                price  = float(item.get("pDPP",    0) or 0)
                volume = float(item.get("pDV",     0) or 0)
                value  = float(item.get("pDJ",     0) or 0)  # 売買代金（円）
                chg_r  = float(item.get("pDYRP",   0) or 0)  # 騰落率(%)
                high   = float(item.get("pDHP",    0) or 0)
                low    = float(item.get("pDLP",    0) or 0)
                open_  = float(item.get("pDOP",    0) or 0)
                prev   = float(item.get("pPRP",    0) or 0)
                time_  = item.get("tDPP:T", "")

                # 売買代金がない場合は現在値×出来高で推計
                if value == 0 and price > 0 and volume > 0:
                    value = price * volume

                if price > 0:
                    all_rows.append({
                        "code":       code,
                        "現在値":     price,
                        "騰落率(%)":  chg_r,
                        "出来高":     volume,
                        "売買代金(億円)": value / 1e8,
                        "高値":       high,
                        "安値":       low,
                        "始値":       open_,
                        "前日終値":   prev,
                        "時刻":       time_,
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


# ── 実行 ──────────────────────────────────────────────────────
if generate or auto_refresh:
    if auto_refresh and not generate:
        time.sleep(60)

    with st.spinner(f"{len(CODES)}銘柄のデータを取得中...（約3〜5秒）"):
        t0 = time.time()
        df = fetch_ranking(sess)
        elapsed = time.time() - t0

    if df is None or df.empty:
        st.error("データを取得できませんでした。")
        st.stop()

    now_str = datetime.now(JST).strftime("%H:%M:%S")
    st.success(f"✅ {len(df)}銘柄取得完了　{now_str}　（{elapsed:.1f}秒）")

    # 上位N件
    df_top = df.head(top_n).copy()

    # ── テーブル表示 ──────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"### 📊 売買代金ランキング上位{top_n}（{now_str}時点）")

    def color_change(val):
        if val > 0:
            return "color: #E74C3C; font-weight: bold"
        elif val < 0:
            return "color: #3498DB; font-weight: bold"
        return ""

    display_df = df_top[["code","現在値","騰落率(%)","売買代金(億円)","出来高","高値","安値"]].copy()
    display_df["売買代金(億円)"] = display_df["売買代金(億円)"].map(lambda x: f"{x:.1f}")
    display_df["出来高"] = display_df["出来高"].map(lambda x: f"{int(x):,}")
    display_df["現在値"] = display_df["現在値"].map(lambda x: f"{x:,.0f}")
    display_df["高値"]   = display_df["高値"].map(lambda x: f"{x:,.0f}")
    display_df["安値"]   = display_df["安値"].map(lambda x: f"{x:,.0f}")
    display_df["騰落率(%)"] = display_df["騰落率(%)"].map(lambda x: f"{x:+.2f}%")
    display_df.columns = ["コード","現在値","騰落率","売買代金(億)","出来高","高値","安値"]

    st.dataframe(
        display_df,
        use_container_width=True,
        height=min(60 + top_n * 35, 800),
    )

    # ── コードコピー用 ────────────────────────────────────────
    st.markdown("---")
    top12_codes  = df_top.head(12)["code"].tolist()
    codes_str    = ",".join(top12_codes)
    st.markdown("### 📋 上位12銘柄コード（チャートアプリ用）")
    st.code(codes_str, language=None)

    # ── 棒グラフ ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📈 売買代金グラフ")

    fig, ax = plt.subplots(figsize=(12, max(4, top_n * 0.3)))
    colors = ["#E74C3C" if v > 0 else "#3498DB"
              for v in df_top["騰落率(%)"]]
    bars = ax.barh(
        range(len(df_top)),
        df_top["売買代金(億円)"],
        color=colors, alpha=0.85
    )
    ax.set_yticks(range(len(df_top)))
    ax.set_yticklabels([f"{i+1}. {c}" for i, c in enumerate(df_top["code"])],
                       fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("売買代金（億円）", fontsize=10)
    ax.set_title(f"売買代金ランキング上位{top_n}　{now_str}時点", fontsize=12, fontweight="bold")
    ax.spines[["top","right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)

    # 値ラベル
    for i, (bar, val) in enumerate(zip(bars, df_top["売買代金(億円)"])):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                f"{val:.0f}億", va="center", fontsize=8)

    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    if auto_refresh:
        st.rerun()
