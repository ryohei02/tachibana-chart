"""
5_売買代金ランキング.py
立花証券API版 場中リアルタイム売買代金ランキング（強化版）

【機能】
- 時価総額上位約140銘柄のリアルタイム売買代金ランキング
- 銘柄名表示（コード埋め込み辞書、高速）
- 規模区分（超大型/大型/中型）
- 20日・60日騰落率（上位N銘柄のみ日足取得して計算）
- 売買代金 前日比・5日平均比（進捗率補正付き）
- 当日騰落率

【進捗率補正の考え方】
  場中は当日売買代金が前日より少なく見える（まだ引けていないため）。
  上位progress_n銘柄の当日売買代金合計 ÷ 前日売買代金合計 = 進捗率
  当日売買代金 ÷ 進捗率 = 終日換算売買代金
  この終日換算値で前日比・5日平均比を計算する。
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
st.caption("時価総額上位約140銘柄を対象 | 進捗率補正あり | 立花証券e支店APIでリアルタイム取得")

# ── ログイン確認 ──────────────────────────────────────────────
sess = require_login()
if sess is None:
    st.stop()

# ══════════════════════════════════════════════════════════════
#  銘柄マスタ（コード埋め込み）
#  (name, size)  size: S=超大型, L=大型, M=中型, ""=ETF等
# ══════════════════════════════════════════════════════════════
ISSUE_MASTER = {
    "7203": ("トヨタ自動車",              "S"),
    "8306": ("三菱UFJフィナンシャル",      "S"),
    "9984": ("ソフトバンクグループ",        "S"),
    "6861": ("キーエンス",                "S"),
    "8316": ("三井住友フィナンシャルG",     "S"),
    "7974": ("任天堂",                    "S"),
    "6758": ("ソニーグループ",             "S"),
    "9432": ("日本電信電話",              "S"),
    "4063": ("信越化学工業",              "S"),
    "6098": ("リクルートHD",             "S"),
    "8411": ("みずほフィナンシャルG",      "S"),
    "9433": ("KDDI",                     "S"),
    "8035": ("東京エレクトロン",           "S"),
    "6367": ("ダイキン工業",              "S"),
    "7267": ("本田技研工業",              "S"),
    "6902": ("デンソー",                  "S"),
    "4661": ("オリエンタルランド",          "S"),
    "9022": ("東海旅客鉄道",              "S"),
    "8766": ("東京海上HD",               "S"),
    "8801": ("三井不動産",               "S"),
    "6954": ("ファナック",               "S"),
    "3382": ("セブン&アイHD",            "S"),
    "4519": ("中外製薬",                 "S"),
    "2914": ("日本たばこ産業",            "S"),
    "6501": ("日立製作所",               "S"),
    "8802": ("三菱地所",                 "S"),
    "6752": ("パナソニックHD",            "S"),
    "6702": ("富士通",                   "S"),
    "9020": ("東日本旅客鉄道",            "S"),
    "8058": ("三菱商事",                 "S"),
    "9983": ("ファーストリテイリング",      "S"),
    "7751": ("キヤノン",                  "L"),
    "7011": ("三菱重工業",               "L"),
    "8031": ("三井物産",                 "L"),
    "5108": ("ブリヂストン",              "L"),
    "8309": ("三井住友トラスト",           "L"),
    "2502": ("アサヒグループHD",          "L"),
    "9021": ("西日本旅客鉄道",            "L"),
    "2503": ("キリンHD",                 "L"),
    "7733": ("オリンパス",               "L"),
    "9434": ("ソフトバンク",              "L"),
    "6503": ("三菱電機",                 "L"),
    "8830": ("住友不動産",               "L"),
    "7270": ("SUBARU",                  "L"),
    "8604": ("野村HD",                  "L"),
    "4507": ("塩野義製薬",               "L"),
    "8591": ("オリックス",               "L"),
    "4183": ("三井化学",                 "L"),
    "6857": ("アドバンテスト",            "L"),
    "7201": ("日産自動車",               "L"),
    "5411": ("JFEホールディングス",       "L"),
    "6645": ("オムロン",                 "L"),
    "8053": ("住友商事",                 "L"),
    "7269": ("スズキ",                   "L"),
    "7182": ("ゆうちょ銀行",             "L"),
    "9101": ("日本郵船",                 "L"),
    "9104": ("商船三井",                 "L"),
    "4543": ("テルモ",                   "L"),
    "6594": ("日本電産",                 "L"),
    "9062": ("日本通運",                 "L"),
    "6762": ("TDK",                     "L"),
    "4568": ("第一三共",                 "L"),
    "9107": ("川崎汽船",                 "L"),
    "6301": ("小松製作所",               "L"),
    "5401": ("日本製鉄",                 "L"),
    "6273": ("SMC",                     "L"),
    "8697": ("日本取引所グループ",         "L"),
    "7735": ("SCREEN Holdings",          "L"),
    "6326": ("クボタ",                   "L"),
    "4452": ("花王",                     "L"),
    "2802": ("味の素",                   "L"),
    "9005": ("東急",                     "L"),
    "7912": ("大日本印刷",               "L"),
    "5713": ("住友金属鉱山",             "L"),
    "4151": ("協和キリン",               "L"),
    "6471": ("日本精工",                 "L"),
    "7832": ("バンダイナムコHD",          "L"),
    "7272": ("ヤマハ発動機",             "L"),
    "7013": ("IHI",                     "L"),
    "3407": ("旭化成",                   "L"),
    "4911": ("資生堂",                   "L"),
    "6302": ("住友重機械工業",            "L"),
    "6361": ("荏原製作所",               "L"),
    "4021": ("日産化学",                 "L"),
    "8015": ("豊田通商",                 "L"),
    "1925": ("大和ハウス工業",            "L"),
    "7741": ("HOYA",                    "L"),
    "4324": ("電通グループ",             "L"),
    "4704": ("トレンドマイクロ",          "M"),
    "6869": ("シスメックス",             "L"),
    "4901": ("富士フイルムHD",            "L"),
    "8750": ("第一生命HD",               "L"),
    "1570": ("日経225レバレッジETF",      ""),
    "3659": ("ネクソン",                 "L"),
    "8267": ("イオン",                   "L"),
    "3099": ("三越伊勢丹HD",             "M"),
    "2413": ("エムスリー",               "L"),
    "8630": ("SOMPOホールディングス",     "L"),
    "6963": ("ローム",                   "L"),
    "4528": ("小野薬品工業",             "M"),
    "6506": ("安川電機",                 "L"),
    "4523": ("エーザイ",                 "L"),
    "7186": ("コンコルディアFG",          "M"),
    "5020": ("ENEOSホールディングス",     "L"),
    "3861": ("王子HD",                  "L"),
    "4005": ("住友化学",                 "L"),
    "5019": ("出光興産",                 "L"),
    "6841": ("横河電機",                 "M"),
    "4042": ("東ソー",                   "M"),
    "5706": ("三井金属鉱業",             "M"),
    "7003": ("三井E&S",                 "M"),
    "3289": ("東急不動産HD",             "M"),
    "4188": ("三菱ケミカルグループ",       "L"),
    "9064": ("ヤマトHD",                "L"),
    "9613": ("NTTデータグループ",         "L"),
    "4689": ("LINEヤフー",              "L"),
    "9502": ("中部電力",                 "L"),
    "9531": ("東京ガス",                 "L"),
    "1928": ("積水ハウス",               "L"),
    "7261": ("マツダ",                   "L"),
    "6460": ("セガサミーHD",             "M"),
    "4385": ("メルカリ",                 "M"),
    "3092": ("ZOZO",                    "M"),
    "2371": ("カカクコム",               "M"),
    "6920": ("レーザーテック",            "L"),
    "6146": ("ディスコ",                 "L"),
    "285A": ("レゾナック・HD",            "L"),
    "4755": ("楽天グループ",             "L"),
    "2269": ("明治HD",                  "L"),
    "9843": ("ニトリHD",                "L"),
    "3401": ("帝人",                     "M"),
    "6753": ("シャープ",                 "L"),
    "7731": ("ニコン",                   "L"),
    "6981": ("村田製作所",               "L"),
    "4503": ("アステラス製薬",            "L"),
    "6976": ("太陽誘電",                 "M"),
    "4004": ("レゾナック",               "L"),
    "6988": ("日東電工",                 "L"),
    "6113": ("アマダ",                   "M"),
    "8252": ("丸井グループ",             "M"),
    "3436": ("SUMCO",                   "M"),
    "5803": ("フジクラ",                 "M"),
    "6971": ("京セラ",                   "L"),
    "4062": ("イビデン",                 "M"),
    "5016": ("JX金属",                  "M"),
    "5802": ("住友電気工業",             "L"),
    "5801": ("古河電気工業",             "M"),
    "6967": ("新光電気工業",             "M"),
    "3086": ("J.フロント リテイリング",   "M"),
    "8355": ("静岡銀行",                 "M"),
    "2651": ("ローソン",                 "M"),
    "3197": ("すかいらーくHD",           "M"),
    "7816": ("スノーピーク",             "M"),
    "2282": ("日本ハム",                 "L"),
    "2875": ("東洋水産",                 "M"),
    "5105": ("TOYO TIRE",               "M"),
}

SIZE_LABEL = {"S": "超大型", "L": "大型", "M": "中型", "": "ETF等"}

# 重複除去・順序保持
seen = set()
CODES = []
for c in ISSUE_MASTER:
    if c not in seen:
        seen.add(c)
        CODES.append(c)

# ── 設定UI ────────────────────────────────────────────────────
st.info(f"対象銘柄数: **{len(CODES)}銘柄** | 更新: {datetime.now(JST).strftime('%H:%M:%S')}")

col_s1, col_s2, col_s3 = st.columns(3)
with col_s1:
    top_n = st.slider("表示件数", min_value=10, max_value=50, value=20, step=5)
with col_s2:
    daily_top_n = st.slider("日足取得（上位N銘柄）", min_value=10, max_value=30, value=20, step=5)
with col_s3:
    progress_n = st.slider("進捗率計算（上位N銘柄）", min_value=5, max_value=20, value=20, step=5)

col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    generate = st.button("🔄 取得・更新", type="primary", use_container_width=True)
with col_btn2:
    auto_refresh = st.checkbox("⏱ 60秒ごとに自動更新", value=False)

debug_mode = st.sidebar.checkbox("🔍 デバッグモード", value=False)


# ══════════════════════════════════════════════════════════════
#  Step1: スナップショット取得
# ══════════════════════════════════════════════════════════════

def fetch_snapshot(sess, codes: list, debug: bool = False) -> pd.DataFrame | None:
    all_rows = []
    batch_size = 50

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        body = sess.price({
            "sCLMID":           "CLMMfdsGetMarketPrice",
            "sTargetIssueCode": ",".join(batch),
            "sTargetColumn":    "pDPP,tDPP:T,pPRP,pDYWP,pDYRP,pDV,pDHP,pDLP,pDOP,pDJ",
        })
        if body.get("p_errno", "-1") != "0":
            if debug:
                st.warning(f"バッチ{i//batch_size+1} エラー: {body.get('p_err')}")
            continue

        for item in body.get("aCLMMfdsMarketPrice", []):
            try:
                code_raw = item.get("sIssueCode", "")
                code = (code_raw[:-1] if (len(code_raw) == 5 and code_raw.endswith("0")
                        and code_raw[:-1].isdigit()) else code_raw)

                price  = float(item.get("pDPP",  0) or 0)
                volume = float(item.get("pDV",   0) or 0)
                pdj    = float(item.get("pDJ",   0) or 0)
                chg_r  = float(item.get("pDYRP", 0) or 0)
                chg_w  = float(item.get("pDYWP", 0) or 0)
                high   = float(item.get("pDHP",  0) or 0)
                low    = float(item.get("pDLP",  0) or 0)
                open_  = float(item.get("pDOP",  0) or 0)
                prev   = float(item.get("pPRP",  0) or 0)
                time_  = item.get("tDPP:T", "")

                if price == 0 and prev > 0:
                    price = prev

                if pdj > 0:
                    value_oku = pdj / 1e8
                elif price > 0 and volume > 0:
                    value_oku = price * volume / 1e8
                else:
                    value_oku = 0.0

                if price > 0 and value_oku > 0:
                    name, size = ISSUE_MASTER.get(code, (code, ""))
                    all_rows.append({
                        "code":          code,
                        "銘柄名":        name,
                        "規模":          SIZE_LABEL.get(size, ""),
                        "現在値":        price,
                        "騰落率(%)":     chg_r,
                        "騰落額":        chg_w,
                        "出来高(千株)":  volume / 1000,
                        "売買代金(億)":  value_oku,
                        "高値":          high,
                        "安値":          low,
                        "始値":          open_,
                        "前日終値":      prev,
                        "時刻":          time_,
                    })
            except (ValueError, TypeError):
                continue
        time.sleep(0.15)

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows)
    df = df[df["売買代金(億)"] > 0]
    df = df.sort_values("売買代金(億)", ascending=False).reset_index(drop=True)
    df.index += 1
    return df


# ══════════════════════════════════════════════════════════════
#  Step2: 日足取得（上位N銘柄のみ）
# ══════════════════════════════════════════════════════════════

def fetch_daily_for_codes(sess, codes: list, debug: bool = False) -> dict:
    """指定コードの日足を取得して {code: DataFrame} を返す"""
    result = {}
    prog = st.progress(0, text="日足データ取得中...")

    for i, code in enumerate(codes):
        body = sess.price({
            "sCLMID":     "CLMMfdsGetMarketPriceHistory",
            "sIssueCode": str(code).strip(),
            "sSizyouC":   "00",
        })

        if body.get("p_errno", "-1") != "0":
            result[code] = None
        else:
            rows = []
            for r in body.get("aCLMMfdsMarketPriceHistory", []):
                try:
                    rows.append({
                        "date":   pd.to_datetime(r["sDate"], format="%Y%m%d"),
                        "close":  float(r["pDPP"]),
                        "volume": float(r["pDV"]),
                    })
                except (KeyError, ValueError):
                    continue

            if rows:
                df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
                df["value_oku"] = df["close"] * df["volume"] / 1e8
                result[code] = df
            else:
                result[code] = None

        prog.progress((i + 1) / len(codes), text=f"{code} ({i+1}/{len(codes)})")
        time.sleep(0.15)

    prog.empty()
    return result


# ══════════════════════════════════════════════════════════════
#  Step3: 指標計算
# ══════════════════════════════════════════════════════════════

def calc_metrics(
    df_rank: pd.DataFrame,
    daily_map: dict,
    progress_n: int,
    debug: bool = False,
) -> pd.DataFrame:
    """日足データから各指標を計算してdf_rankに追加する"""
    df = df_rank.copy()

    # 初期化
    for col in ["20日騰落(%)", "60日騰落(%)", "前日売買代金(億)", "5日平均(億)", "前日比(%)", "5日平均比(%)"]:
        df[col] = np.nan

    # ── 各銘柄の騰落率・前日売買代金・5日平均を計算 ──────────
    for idx in df.index:
        code  = df.loc[idx, "code"]
        daily = daily_map.get(code)
        if daily is None or len(daily) < 2:
            continue

        cur_price = df.loc[idx, "現在値"]

        # 20日・60日騰落率（日足の終値ベース）
        if len(daily) >= 21:
            p20 = daily["close"].iloc[-21]
            if p20 > 0:
                df.loc[idx, "20日騰落(%)"] = (cur_price / p20 - 1) * 100
        if len(daily) >= 61:
            p60 = daily["close"].iloc[-61]
            if p60 > 0:
                df.loc[idx, "60日騰落(%)"] = (cur_price / p60 - 1) * 100

        # 前日売買代金・5日平均（日足の最終確定日 = iloc[-1]）
        df.loc[idx, "前日売買代金(億)"] = daily["value_oku"].iloc[-1]
        df.loc[idx, "5日平均(億)"]      = daily["value_oku"].iloc[-5:].mean() if len(daily) >= 5 else daily["value_oku"].mean()

    # ── 進捗率計算 ────────────────────────────────────────────
    top_codes  = df.head(progress_n)["code"].tolist()
    top_mask   = df["code"].isin(top_codes)
    today_sum  = df.loc[top_mask, "売買代金(億)"].sum()
    prev_sum   = df.loc[top_mask, "前日売買代金(億)"].sum()

    progress_rate = (today_sum / prev_sum) if (prev_sum > 0 and today_sum > 0) else 1.0
    df["進捗率"] = progress_rate

    if debug:
        st.info(
            f"📊 進捗率 | 上位{progress_n}銘柄 | "
            f"当日: {today_sum:.0f}億 / 前日: {prev_sum:.0f}億 "
            f"= **{progress_rate*100:.1f}%**"
        )

    # ── 前日比・5日平均比（終日換算後） ──────────────────────
    for idx in df.index:
        today_val = df.loc[idx, "売買代金(億)"]
        prev_val  = df.loc[idx, "前日売買代金(億)"]
        avg5_val  = df.loc[idx, "5日平均(億)"]

        if progress_rate > 0:
            projected = today_val / progress_rate  # 終日換算
            if not pd.isna(prev_val) and prev_val > 0:
                df.loc[idx, "前日比(%)"] = (projected / prev_val - 1) * 100
            if not pd.isna(avg5_val) and avg5_val > 0:
                df.loc[idx, "5日平均比(%)"] = (projected / avg5_val - 1) * 100

    return df


# ══════════════════════════════════════════════════════════════
#  表示関数
# ══════════════════════════════════════════════════════════════

def _color_pct(val, decimals: int = 0) -> str:
    if pd.isna(val):
        return '<span style="color:#666">-</span>'
    sign  = "+" if val >= 0 else ""
    color = "#FF6B6B" if val > 0 else ("#6B9FFF" if val < 0 else "#AAAAAA")
    fmt   = f"{sign}{val:.{decimals}f}%"
    return f'<span style="color:{color};font-weight:bold">{fmt}</span>'


def display_ranking(df: pd.DataFrame, top_n: int, now_str: str, debug: bool):
    df_top = df.head(top_n).copy().reset_index(drop=True)
    df_top.index += 1

    st.markdown("---")
    st.markdown(f"### 📊 売買代金ランキング上位{top_n}（{now_str}時点）")

    # 進捗率バッジ
    if "進捗率" in df_top.columns and not df_top.empty:
        rate = df_top["進捗率"].iloc[0]
        if not pd.isna(rate):
            st.caption(
                f"📈 進捗率: **{rate*100:.1f}%**（上位{df_top.shape[0]}銘柄合計ベース）"
                f"　前日比・5日平均比は終日換算後の値"
            )

    has_daily = "前日比(%)" in df_top.columns

    # ── HTMLテーブル ──────────────────────────────────────────
    rows_html = ""
    size_colors = {"超大型": "#FF8C00", "大型": "#4CAF50", "中型": "#2196F3", "ETF等": "#888", "": "#888"}

    for i, row in df_top.iterrows():
        chg_html  = _color_pct(row["騰落率(%)"], decimals=2)
        prev_html = _color_pct(row.get("前日比(%)"))     if has_daily else '<span style="color:#666">-</span>'
        avg5_html = _color_pct(row.get("5日平均比(%)"))  if has_daily else '<span style="color:#666">-</span>'
        d20_html  = _color_pct(row.get("20日騰落(%)"))   if has_daily else '<span style="color:#666">-</span>'
        d60_html  = _color_pct(row.get("60日騰落(%)"))   if has_daily else '<span style="color:#666">-</span>'
        vol_str   = f'{int(row["出来高(千株)"]):,}' if not pd.isna(row["出来高(千株)"]) else "-"
        s_color   = size_colors.get(row["規模"], "#888")

        rows_html += f"""
        <tr>
          <td style="text-align:center;color:#FFD700;font-weight:bold;width:40px">{i}</td>
          <td style="text-align:left;max-width:150px;overflow:hidden;white-space:nowrap">{row['銘柄名']}</td>
          <td style="text-align:center;color:#CCC">{row['code']}</td>
          <td style="text-align:center;color:{s_color};font-size:0.82em;white-space:nowrap">{row['規模']}</td>
          <td style="text-align:right;font-weight:bold">{row['売買代金(億)']:.0f}</td>
          <td style="text-align:right">{prev_html}</td>
          <td style="text-align:right">{avg5_html}</td>
          <td style="text-align:right">{chg_html}</td>
          <td style="text-align:right">{d20_html}</td>
          <td style="text-align:right">{d60_html}</td>
          <td style="text-align:right;color:#AAA;font-size:0.85em">{vol_str}</td>
        </tr>"""

    table_html = f"""
    <style>
      .rtable {{ width:100%;border-collapse:collapse;font-size:0.9em; }}
      .rtable th {{
        background:#1E2A3A;color:#AAC4E8;padding:8px 10px;
        text-align:center;border-bottom:2px solid #334;white-space:nowrap;
      }}
      .rtable td {{ padding:6px 10px;border-bottom:1px solid #2A3344;color:#E0E0E0; }}
      .rtable tr:hover td {{ background:#1E2835; }}
    </style>
    <table class="rtable">
      <thead><tr>
        <th>順位</th><th>銘柄名</th><th>コード</th><th>規模</th>
        <th>売買代金(億)</th><th>前日比*</th><th>5日平均比*</th>
        <th>当日騰落</th><th>20日騰落</th><th>60日騰落</th>
        <th>出来高(千株)</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="color:#888;font-size:0.78em;margin-top:4px">* 進捗率補正済み（終日換算値で比較）</p>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    # ── コードコピー ──────────────────────────────────────────
    st.markdown("---")
    top18 = df_top.head(18)["code"].tolist()
    st.markdown("### 📋 上位18銘柄コード（チャートページ用）")
    st.code(",".join(top18), language=None)

    # ── 棒グラフ ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📈 売買代金グラフ")

    fig, ax = plt.subplots(figsize=(12, max(4, len(df_top) * 0.40)))
    bar_colors = ["#FF6B6B" if v > 0 else ("#6B9FFF" if v < 0 else "#888888")
                  for v in df_top["騰落率(%)"]]
    bars = ax.barh(range(len(df_top)), df_top["売買代金(億)"], color=bar_colors, alpha=0.85)

    labels = [
        f"{i+1}. {row['銘柄名'][:10]}({row['code']})  {row['騰落率(%)']:+.1f}%"
        for i, (_, row) in enumerate(df_top.iterrows())
    ]
    ax.set_yticks(range(len(df_top)))
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlabel("売買代金（億円）", fontsize=10)
    ax.set_title(f"売買代金ランキング上位{len(df_top)}　{now_str}時点", fontsize=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)

    max_val = df_top["売買代金(億)"].max()
    for bar, val in zip(bars, df_top["売買代金(億)"]):
        ax.text(bar.get_width() + max_val * 0.005,
                bar.get_y() + bar.get_height() / 2,
                f"{val:.0f}億", va="center", fontsize=8)

    ax.legend(handles=[
        mpatches.Patch(color="#FF6B6B", label="上昇"),
        mpatches.Patch(color="#6B9FFF", label="下落"),
    ], loc="lower right", fontsize=9)

    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    # ── デバッグ: 日足計算値確認 ─────────────────────────────
    if debug and has_daily:
        with st.expander("🔍 日足計算値確認（上位10件）"):
            dbg = df_top.head(10)[[
                "code", "銘柄名", "売買代金(億)", "前日売買代金(億)",
                "5日平均(億)", "前日比(%)", "5日平均比(%)", "20日騰落(%)", "60日騰落(%)"
            ]].round(1)
            st.dataframe(dbg)


# ══════════════════════════════════════════════════════════════
#  メイン実行
# ══════════════════════════════════════════════════════════════

if generate or (auto_refresh and "last_fetch" not in st.session_state):

    # Step1: スナップショット取得
    with st.spinner(f"📡 {len(CODES)}銘柄のスナップショット取得中..."):
        t0 = time.time()
        df_snap = fetch_snapshot(sess, CODES, debug=debug_mode)

    if df_snap is None or df_snap.empty:
        st.error("スナップショット取得失敗。デバッグモードをONにして再試行してください。")
        st.stop()

    snap_sec = time.time() - t0
    now_str  = datetime.now(JST).strftime("%H:%M:%S")
    st.success(f"✅ スナップショット: {len(df_snap)}銘柄　（{snap_sec:.1f}秒）")

    # Step2: 上位N銘柄の日足取得
    top_codes_for_daily = df_snap.head(daily_top_n)["code"].tolist()
    with st.spinner(f"📈 上位{daily_top_n}銘柄の日足取得中...（約{daily_top_n * 0.2:.0f}秒）"):
        t1 = time.time()
        daily_map = fetch_daily_for_codes(sess, top_codes_for_daily, debug=debug_mode)
    daily_sec = time.time() - t1
    st.success(f"✅ 日足取得完了　（{daily_sec:.1f}秒）")

    # Step3: 指標計算
    with st.spinner("🧮 指標計算中..."):
        df_final = calc_metrics(df_snap, daily_map, progress_n=progress_n, debug=debug_mode)

    total_sec = time.time() - t0
    st.success(f"✅ 全処理完了　{now_str}　合計 {total_sec:.1f}秒")

    st.session_state["ranking_df"]   = df_final
    st.session_state["ranking_time"] = now_str
    st.session_state["last_fetch"]   = time.time()

# 保存済みデータがあれば表示
if "ranking_df" in st.session_state:
    display_ranking(
        st.session_state["ranking_df"],
        top_n,
        st.session_state.get("ranking_time", ""),
        debug=debug_mode,
    )

# 自動更新
if auto_refresh:
    last      = st.session_state.get("last_fetch", 0)
    remaining = 60 - int(time.time() - last)
    if remaining > 0:
        st.caption(f"⏱ 次の自動更新まで {remaining} 秒")
        time.sleep(1)
        st.rerun()
    else:
        del st.session_state["last_fetch"]
        st.rerun()
