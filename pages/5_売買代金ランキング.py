"""
5_売買代金ランキング.py
立花証券API版 場中リアルタイム売買代金ランキング（強化版）

【機能】
- 時価総額上位約140銘柄のリアルタイム売買代金ランキング
- 銘柄名・規模・業種表示（コード埋め込み辞書）
- 20日・60日騰落率（上位N銘柄のみ日足取得して計算）
- 売買代金 前日比・5日平均比（進捗率補正付き）
- ランキング画像を3枚（1-20位・21-40位・41-60位）生成・ダウンロード
"""

import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import io
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import time
from datetime import datetime, timezone, timedelta

from chart_utils import setup_japanese_font
from login_ui import require_login

plt.rcParams["font.family"] = setup_japanese_font()
JST = timezone(timedelta(hours=9))

st.set_page_config(page_title="売買代金ランキング", page_icon="🏆", layout="wide")
st.title("🏆 売買代金ランキング（場中リアルタイム）")
st.caption("時価総額上位約140銘柄を対象 | 進捗率補正あり | 立花証券e支店APIでリアルタイム取得")

sess = require_login()
if sess is None:
    st.stop()

# ══════════════════════════════════════════════════════════════
#  銘柄マスタ  (name, size, sector)
#  size:   S=超大型  L=大型  M=中型  ""=ETF等
#  sector: 業種（東証33業種ベース、略称）
# ══════════════════════════════════════════════════════════════
ISSUE_MASTER = {
    # code: (銘柄名, 規模, 業種)
    "7203": ("トヨタ自動車",          "S", "輸送用機器"),
    "8306": ("三菱UFJフィナンシャル", "S", "銀行"),
    "9984": ("ソフトバンクグループ",   "S", "情報通信"),
    "6861": ("キーエンス",            "S", "電機・精密"),
    "8316": ("三井住友フィナンシャルG","S", "銀行"),
    "7974": ("任天堂",                "S", "その他製品"),
    "6758": ("ソニーグループ",         "S", "電機・精密"),
    "9432": ("日本電信電話",          "S", "情報通信"),
    "4063": ("信越化学工業",          "S", "化学"),
    "6098": ("リクルートHD",          "S", "情報通信"),
    "8411": ("みずほフィナンシャルG",  "S", "銀行"),
    "9433": ("KDDI",                  "S", "情報通信"),
    "8035": ("東京エレクトロン",       "S", "電機・精密"),
    "6367": ("ダイキン工業",          "S", "機械"),
    "7267": ("本田技研工業",          "S", "輸送用機器"),
    "6902": ("デンソー",              "S", "輸送用機器"),
    "4661": ("オリエンタルランド",     "S", "サービス"),
    "9022": ("東海旅客鉄道",          "S", "陸運"),
    "8766": ("東京海上HD",            "S", "保険"),
    "8801": ("三井不動産",            "S", "不動産"),
    "6954": ("ファナック",            "S", "電機・精密"),
    "3382": ("セブン&アイHD",         "S", "小売"),
    "4519": ("中外製薬",              "S", "医薬品"),
    "2914": ("日本たばこ産業",        "S", "食品"),
    "6501": ("日立製作所",            "S", "電機・精密"),
    "8802": ("三菱地所",              "S", "不動産"),
    "6752": ("パナソニックHD",         "S", "電機・精密"),
    "6702": ("富士通",                "S", "電機・精密"),
    "9020": ("東日本旅客鉄道",        "S", "陸運"),
    "8058": ("三菱商事",              "S", "商社"),
    "9983": ("ファーストリテイリング", "S", "小売"),
    "7751": ("キヤノン",              "L", "電機・精密"),
    "7011": ("三菱重工業",            "L", "機械"),
    "8031": ("三井物産",              "L", "商社"),
    "5108": ("ブリヂストン",          "L", "ゴム"),
    "8309": ("三井住友トラスト",       "L", "銀行"),
    "2502": ("アサヒグループHD",       "L", "食品"),
    "9021": ("西日本旅客鉄道",        "L", "陸運"),
    "2503": ("キリンHD",              "L", "食品"),
    "7733": ("オリンパス",            "L", "電機・精密"),
    "9434": ("ソフトバンク",          "L", "情報通信"),
    "6503": ("三菱電機",              "L", "電機・精密"),
    "8830": ("住友不動産",            "L", "不動産"),
    "7270": ("SUBARU",               "L", "輸送用機器"),
    "8604": ("野村HD",                "L", "証券"),
    "4507": ("塩野義製薬",            "L", "医薬品"),
    "8591": ("オリックス",            "L", "その他金融"),
    "4183": ("三井化学",              "L", "化学"),
    "6857": ("アドバンテスト",         "L", "電機・精密"),
    "7201": ("日産自動車",            "L", "輸送用機器"),
    "5411": ("JFEホールディングス",    "L", "鉄鋼・非鉄"),
    "6645": ("オムロン",              "L", "電機・精密"),
    "8053": ("住友商事",              "L", "商社"),
    "7269": ("スズキ",               "L", "輸送用機器"),
    "7182": ("ゆうちょ銀行",          "L", "銀行"),
    "9101": ("日本郵船",              "L", "海運"),
    "9104": ("商船三井",              "L", "海運"),
    "4543": ("テルモ",               "L", "電機・精密"),
    "6594": ("日本電産",              "L", "電機・精密"),
    "9062": ("日本通運",              "L", "陸運"),
    "6762": ("TDK",                  "L", "電機・精密"),
    "4568": ("第一三共",              "L", "医薬品"),
    "9107": ("川崎汽船",              "L", "海運"),
    "6301": ("小松製作所",            "L", "機械"),
    "5401": ("日本製鉄",              "L", "鉄鋼・非鉄"),
    "6273": ("SMC",                  "L", "機械"),
    "8697": ("日本取引所グループ",     "L", "証券"),
    "7735": ("SCREEN Holdings",       "L", "電機・精密"),
    "6326": ("クボタ",               "L", "機械"),
    "4452": ("花王",                 "L", "化学"),
    "2802": ("味の素",               "L", "食品"),
    "9005": ("東急",                 "L", "陸運"),
    "7912": ("大日本印刷",            "L", "その他製品"),
    "5713": ("住友金属鉱山",          "L", "鉄鋼・非鉄"),
    "4151": ("協和キリン",            "L", "医薬品"),
    "6471": ("日本精工",              "L", "機械"),
    "7832": ("バンダイナムコHD",       "L", "その他製品"),
    "7272": ("ヤマハ発動機",          "L", "輸送用機器"),
    "7013": ("IHI",                  "L", "機械"),
    "3407": ("旭化成",               "L", "化学"),
    "4911": ("資生堂",               "L", "化学"),
    "6302": ("住友重機械工業",        "L", "機械"),
    "6361": ("荏原製作所",            "L", "機械"),
    "4021": ("日産化学",              "L", "化学"),
    "8015": ("豊田通商",              "L", "商社"),
    "1925": ("大和ハウス工業",        "L", "建設"),
    "7741": ("HOYA",                 "L", "電機・精密"),
    "4324": ("電通グループ",          "L", "サービス"),
    "4704": ("トレンドマイクロ",       "M", "情報通信"),
    "6869": ("シスメックス",          "L", "電機・精密"),
    "4901": ("富士フイルムHD",        "L", "化学"),
    "8750": ("第一生命HD",            "L", "保険"),
    "1570": ("日経225レバレッジETF",  "",  "ETF"),
    "3659": ("ネクソン",              "L", "情報通信"),
    "8267": ("イオン",               "L", "小売"),
    "3099": ("三越伊勢丹HD",          "M", "小売"),
    "2413": ("エムスリー",            "L", "サービス"),
    "8630": ("SOMPOホールディングス", "L", "保険"),
    "6963": ("ローム",               "L", "電機・精密"),
    "4528": ("小野薬品工業",          "M", "医薬品"),
    "6506": ("安川電機",              "L", "電機・精密"),
    "4523": ("エーザイ",              "L", "医薬品"),
    "7186": ("コンコルディアFG",       "M", "銀行"),
    "5020": ("ENEOSホールディングス", "L", "石油・資源"),
    "3861": ("王子HD",               "L", "パルプ・紙"),
    "4005": ("住友化学",              "L", "化学"),
    "5019": ("出光興産",              "L", "石油・資源"),
    "6841": ("横河電機",              "M", "電機・精密"),
    "4042": ("東ソー",               "M", "化学"),
    "5706": ("三井金属鉱業",          "M", "鉄鋼・非鉄"),
    "7003": ("三井E&S",              "M", "機械"),
    "3289": ("東急不動産HD",          "M", "不動産"),
    "4188": ("三菱ケミカルグループ",   "L", "化学"),
    "9064": ("ヤマトHD",              "L", "陸運"),
    "9613": ("NTTデータグループ",      "L", "情報通信"),
    "4689": ("LINEヤフー",            "L", "情報通信"),
    "9502": ("中部電力",              "L", "電力・ガス"),
    "9531": ("東京ガス",              "L", "電力・ガス"),
    "1928": ("積水ハウス",            "L", "建設"),
    "7261": ("マツダ",               "L", "輸送用機器"),
    "6460": ("セガサミーHD",          "M", "その他製品"),
    "4385": ("メルカリ",              "M", "情報通信"),
    "3092": ("ZOZO",                 "M", "小売"),
    "2371": ("カカクコム",            "M", "情報通信"),
    "6920": ("レーザーテック",         "L", "電機・精密"),
    "6146": ("ディスコ",              "L", "電機・精密"),
    "285A": ("キオクシアHD",          "L", "電機・精密"),
    "4755": ("楽天グループ",          "L", "情報通信"),
    "2269": ("明治HD",               "L", "食品"),
    "9843": ("ニトリHD",              "L", "小売"),
    "3401": ("帝人",                 "M", "化学"),
    "6753": ("シャープ",              "L", "電機・精密"),
    "7731": ("ニコン",               "L", "電機・精密"),
    "6981": ("村田製作所",            "L", "電機・精密"),
    "4503": ("アステラス製薬",         "L", "医薬品"),
    "6976": ("太陽誘電",              "M", "電機・精密"),
    "4004": ("レゾナック",            "L", "化学"),
    "6988": ("日東電工",              "L", "化学"),
    "6113": ("アマダ",               "M", "機械"),
    "8252": ("丸井グループ",          "M", "小売"),
    "3436": ("SUMCO",                "M", "電機・精密"),
    "5803": ("フジクラ",              "M", "鉄鋼・非鉄"),
    "6971": ("京セラ",               "L", "電機・精密"),
    "4062": ("イビデン",              "M", "電機・精密"),
    "5016": ("JX金属",               "M", "鉄鋼・非鉄"),
    "5802": ("住友電気工業",          "L", "鉄鋼・非鉄"),
    "5801": ("古河電気工業",          "M", "鉄鋼・非鉄"),
    "6967": ("新光電気工業",          "M", "電機・精密"),
    "3086": ("J.フロント リテイリング","M", "小売"),
    "8355": ("静岡銀行",              "M", "銀行"),
    "2651": ("ローソン",              "M", "小売"),
    "3197": ("すかいらーくHD",        "M", "サービス"),
    "7816": ("スノーピーク",          "M", "その他製品"),
    "2282": ("日本ハム",              "L", "食品"),
    "2875": ("東洋水産",              "M", "食品"),
    "5105": ("TOYO TIRE",            "M", "ゴム"),
}

SIZE_LABEL = {"S": "超大型", "L": "大型", "M": "中型", "": "ETF等"}

seen = set(); CODES = []
for c in ISSUE_MASTER:
    if c not in seen:
        seen.add(c); CODES.append(c)

# ── UI ───────────────────────────────────────────────────────
st.info(f"対象銘柄数: **{len(CODES)}銘柄** | 更新: {datetime.now(JST).strftime('%H:%M:%S')}")

col_s1, col_s2 = st.columns(2)
with col_s1:
    top_n      = st.slider("表示件数", 10, 60, 60, 10)
with col_s2:
    progress_n = st.slider("進捗率計算（上位N銘柄）", 5, 20, 20, 5)
daily_top_n = 60  # 日足は常に上位60銘柄取得

col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    generate = st.button("🔄 取得・更新", type="primary", use_container_width=True)
with col_btn2:
    auto_refresh = st.checkbox("⏱ 60秒ごとに自動更新", value=False)

debug_mode = st.sidebar.checkbox("🔍 デバッグモード", value=False)


# ══════════════════════════════════════════════════════════════
#  Step1: スナップショット取得
# ══════════════════════════════════════════════════════════════
def fetch_snapshot(sess, codes, debug=False):
    all_rows = []
    for i in range(0, len(codes), 50):
        batch = codes[i:i+50]
        body = sess.price({
            "sCLMID":           "CLMMfdsGetMarketPrice",
            "sTargetIssueCode": ",".join(batch),
            "sTargetColumn":    "pDPP,tDPP:T,pPRP,pDYWP,pDYRP,pDV,pDHP,pDLP,pDOP,pDJ",
        })
        if body.get("p_errno", "-1") != "0":
            if debug: st.warning(f"バッチエラー: {body.get('p_err')}")
            continue
        for item in body.get("aCLMMfdsMarketPrice", []):
            try:
                cr = item.get("sIssueCode", "")
                code = cr[:-1] if (len(cr)==5 and cr.endswith("0") and cr[:-1].isdigit()) else cr
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
                if price == 0 and prev > 0: price = prev
                value_oku = (pdj/1e8 if pdj > 0
                             else price*volume/1e8 if price > 0 and volume > 0
                             else 0.0)
                if price > 0 and value_oku > 0:
                    name, size, sector = ISSUE_MASTER.get(code, (code, "", ""))
                    all_rows.append({
                        "code": code, "銘柄名": name,
                        "規模": SIZE_LABEL.get(size, ""), "業種": sector,
                        "現在値": price, "騰落率(%)": chg_r, "騰落額": chg_w,
                        "出来高(千株)": volume/1000, "売買代金(億)": value_oku,
                        "高値": high, "安値": low, "始値": open_,
                        "前日終値": prev, "時刻": time_,
                    })
            except (ValueError, TypeError):
                continue
        time.sleep(0.15)

    if not all_rows: return None
    df = pd.DataFrame(all_rows)
    df = df[df["売買代金(億)"] > 0].sort_values("売買代金(億)", ascending=False).reset_index(drop=True)
    df.index += 1
    return df


# ══════════════════════════════════════════════════════════════
#  Step2: 日足取得
# ══════════════════════════════════════════════════════════════
def fetch_daily_for_codes(sess, codes, debug=False):
    result = {}
    prog = st.progress(0, text="日足データ取得中...")
    for i, code in enumerate(codes):
        # sleepを0.05秒に短縮（秒20件ペース）
        # エラー時は0.3秒待ってリトライ1回
        for attempt in range(2):
            body = sess.price({
                "sCLMID": "CLMMfdsGetMarketPriceHistory",
                "sIssueCode": str(code).strip(), "sSizyouC": "00",
            })
            if body.get("p_errno", "-1") == "0":
                break
            time.sleep(0.3)  # レート超過時は少し待つ

        if body.get("p_errno", "-1") != "0":
            result[code] = None
        else:
            rows = []
            for r in body.get("aCLMMfdsMarketPriceHistory", []):
                try:
                    rows.append({
                        "date":  pd.to_datetime(r["sDate"], format="%Y%m%d"),
                        "close": float(r["pDPP"]), "volume": float(r["pDV"]),
                    })
                except (KeyError, ValueError):
                    continue
            if rows:
                df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
                df["value_oku"] = df["close"] * df["volume"] / 1e8
                result[code] = df
            else:
                result[code] = None
        prog.progress((i+1)/len(codes), text=f"{code} ({i+1}/{len(codes)})")
        time.sleep(0.05)  # 0.15→0.05秒（秒20件ペース）
    prog.empty()
    return result


# ══════════════════════════════════════════════════════════════
#  Step3: 指標計算
# ══════════════════════════════════════════════════════════════
def calc_metrics(df_rank, daily_map, progress_n, debug=False):
    df = df_rank.copy()
    for col in ["20日騰落(%)", "60日騰落(%)", "前日売買代金(億)", "5日平均(億)", "前日比(%)", "5日平均比(%)"]:
        df[col] = np.nan

    for idx in df.index:
        code  = df.loc[idx, "code"]
        daily = daily_map.get(code)
        if daily is None or len(daily) < 2: continue
        cur = df.loc[idx, "現在値"]
        if len(daily) >= 21:
            p20 = daily["close"].iloc[-21]
            if p20 > 0: df.loc[idx, "20日騰落(%)"] = (cur/p20 - 1)*100
        if len(daily) >= 61:
            p60 = daily["close"].iloc[-61]
            if p60 > 0: df.loc[idx, "60日騰落(%)"] = (cur/p60 - 1)*100
        df.loc[idx, "前日売買代金(億)"] = daily["value_oku"].iloc[-1]
        df.loc[idx, "5日平均(億)"] = daily["value_oku"].iloc[-5:].mean() if len(daily) >= 5 else daily["value_oku"].mean()

    top_codes = df.head(progress_n)["code"].tolist()
    mask = df["code"].isin(top_codes)
    today_sum = df.loc[mask, "売買代金(億)"].sum()
    prev_sum  = df.loc[mask, "前日売買代金(億)"].sum()
    rate = (today_sum/prev_sum) if (prev_sum > 0 and today_sum > 0) else 1.0
    df["進捗率"] = rate

    if debug:
        st.info(f"📊 進捗率 | 上位{progress_n}銘柄 | 当日: {today_sum:.0f}億 / 前日: {prev_sum:.0f}億 = **{rate*100:.1f}%**")

    for idx in df.index:
        tv = df.loc[idx, "売買代金(億)"]
        pv = df.loc[idx, "前日売買代金(億)"]
        av = df.loc[idx, "5日平均(億)"]
        if rate > 0:
            proj = tv / rate
            if not pd.isna(pv) and pv > 0: df.loc[idx, "前日比(%)"]    = (proj/pv - 1)*100
            if not pd.isna(av) and av > 0: df.loc[idx, "5日平均比(%)"] = (proj/av - 1)*100
    return df


# ══════════════════════════════════════════════════════════════
#  画像生成：1枚あたり20銘柄の表形式ランキング画像
# ══════════════════════════════════════════════════════════════
def _pct_color(val):
    if pd.isna(val): return "#888888"
    return "#FF5555" if val > 0 else ("#5599FF" if val < 0 else "#AAAAAA")

def _pct_str(val, dec=0):
    if pd.isna(val): return "-"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.{dec}f}%"

def build_ranking_image(df_slice: pd.DataFrame, title: str, now_str: str, progress_rate: float) -> bytes:
    """
    20銘柄分のランキング画像をPNGバイト列で返す。
    参考画像に近いダーク背景の表形式レイアウト。
    """
    n = len(df_slice)
    fig_h = 1.2 + n * 0.42  # 行数に応じた高さ
    fig = plt.figure(figsize=(20, fig_h), facecolor="#0D1117")
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("#0D1117")
    ax.axis("off")

    # ── ヘッダー ────────────────────────────────────────────
    fig.text(0.02, 0.97, f"売買代金ランキング — {title}",
             color="white", fontsize=16, fontweight="bold", va="top")
    fig.text(0.02, 0.91,
             f"進捗率: {progress_rate*100:.1f}%（補正+{1/progress_rate:.1f}倍）　"
             f"＊前日比は進捗率補正済み　{now_str}現在",
             color="#888888", fontsize=9, va="top")

    # ── 列定義 [label, x位置, align] ────────────────────────
    # 現在値を当日騰落の左に追加、順位左の余白列を削除
    cols = [
        ("順位",          0.022, "center"),
        ("銘柄名",        0.095, "left"),
        ("コード",        0.200, "center"),
        ("規模",          0.248, "center"),
        ("業種",          0.310, "center"),
        ("売買代金(億)",  0.390, "right"),
        ("前日比*",       0.455, "right"),
        ("5日平均比*",    0.520, "right"),
        ("出来高(千株)",  0.595, "right"),
        ("現在値",        0.665, "right"),
        ("当日騰落",      0.740, "right"),
        ("20日騰落",      0.815, "right"),
        ("60日騰落",      0.888, "right"),
    ]

    # ヘッダー行のy座標
    header_y = 0.84
    for label, xc, align in cols:
        fig.text(xc, header_y, label, color="#7799BB", fontsize=8.5,
                 fontweight="bold", ha=align, va="top",
                 transform=fig.transFigure)

    # 区切り線
    line_ax = fig.add_axes([0.01, header_y - 0.015, 0.98, 0.002])
    line_ax.set_facecolor("#334455")
    line_ax.axis("off")

    # ── データ行 ───────────────────────────────────────────
    row_h   = (header_y - 0.06) / (n + 0.5)  # 1行あたりの高さ
    size_colors = {"超大型": "#FF8C00", "大型": "#44BB66", "中型": "#4488FF", "ETF等": "#888888", "": "#888888"}

    for ri, (_, row) in enumerate(df_slice.iterrows()):
        y = header_y - 0.025 - row_h * (ri + 0.8)

        # 偶数行に薄い背景
        if ri % 2 == 1:
            bg = fig.add_axes([0.01, y - row_h*0.35, 0.98, row_h*0.85])
            bg.set_facecolor("#151D28")
            bg.axis("off")

        rank    = int(row["rank"])   # build_ranking_image呼び出し時にrank列として渡す
        name    = str(row["銘柄名"])[:12]
        code    = str(row["code"])
        size    = str(row["規模"])
        sector  = str(row["業種"])[:6]
        val_oku = row["売買代金(億)"]
        price   = row["現在値"]
        chg_r   = row["騰落率(%)"]
        prev_r  = row.get("前日比(%)", np.nan)
        avg5_r  = row.get("5日平均比(%)", np.nan)
        vol_k   = row["出来高(千株)"]
        d20     = row.get("20日騰落(%)", np.nan)
        d60     = row.get("60日騰落(%)", np.nan)

        s_color = size_colors.get(size, "#888888")

        # 順位（1〜3位はゴールド/シルバー/ブロンズ）
        rank_color = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}.get(rank, "#CCCCCC")
        fig.text(cols[0][1], y, str(rank),   color=rank_color,  fontsize=9, fontweight="bold", ha="center", va="center", transform=fig.transFigure)
        fig.text(cols[1][1], y, name,        color="#E8E8E8",   fontsize=9, ha="left",   va="center", transform=fig.transFigure)
        fig.text(cols[2][1], y, code,        color="#AABBCC",   fontsize=8.5, ha="center", va="center", transform=fig.transFigure)
        fig.text(cols[3][1], y, size,        color=s_color,     fontsize=8, ha="center", va="center", transform=fig.transFigure)
        fig.text(cols[4][1], y, sector,      color="#99AACC",   fontsize=8, ha="center", va="center", transform=fig.transFigure)
        fig.text(cols[5][1], y, f"{val_oku:.0f}", color="#FFFFFF", fontsize=9, fontweight="bold", ha="right", va="center", transform=fig.transFigure)
        fig.text(cols[6][1], y, _pct_str(prev_r), color=_pct_color(prev_r), fontsize=9, fontweight="bold", ha="right", va="center", transform=fig.transFigure)
        fig.text(cols[7][1], y, _pct_str(avg5_r), color=_pct_color(avg5_r), fontsize=9, fontweight="bold", ha="right", va="center", transform=fig.transFigure)
        vol_str = f"{int(vol_k):,}" if not pd.isna(vol_k) else "-"
        fig.text(cols[8][1], y, vol_str,     color="#AAAAAA",   fontsize=8.5, ha="right", va="center", transform=fig.transFigure)
        # 現在値
        price_str = f"{price:,.0f}" if not pd.isna(price) and price > 0 else "-"
        fig.text(cols[9][1], y, price_str,   color="#DDDDDD",   fontsize=9, ha="right", va="center", transform=fig.transFigure)
        # 当日騰落
        fig.text(cols[10][1], y, _pct_str(chg_r, dec=2), color=_pct_color(chg_r), fontsize=9, fontweight="bold", ha="right", va="center", transform=fig.transFigure)
        # 20日騰落
        fig.text(cols[11][1], y, _pct_str(d20), color=_pct_color(d20), fontsize=9, fontweight="bold", ha="right", va="center", transform=fig.transFigure)
        # 60日騰落
        fig.text(cols[12][1], y, _pct_str(d60), color=_pct_color(d60), fontsize=9, fontweight="bold", ha="right", va="center", transform=fig.transFigure)

    # フッター
    fig.text(0.98, 0.015, "データ: 立花証券e支店API　＊前日比・5日平均比は進捗率補正済み（終日換算）",
             color="#555555", fontsize=7.5, ha="right", va="bottom", transform=fig.transFigure)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="#0D1117", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════
#  表示関数（HTMLテーブル）
# ══════════════════════════════════════════════════════════════
def _color_pct(val, decimals=0):
    if pd.isna(val): return '<span style="color:#666">-</span>'
    sign  = "+" if val >= 0 else ""
    color = "#FF6B6B" if val > 0 else ("#6B9FFF" if val < 0 else "#AAAAAA")
    return f'<span style="color:{color};font-weight:bold">{sign}{val:.{decimals}f}%</span>'

def display_ranking(df, top_n, now_str, debug):
    df_top = df.head(top_n).copy().reset_index(drop=True)
    df_top.index += 1
    has_daily = "前日比(%)" in df_top.columns
    progress_rate = df_top["進捗率"].iloc[0] if "進捗率" in df_top.columns and not df_top.empty else 1.0

    st.markdown("---")
    st.markdown(f"### 📊 売買代金ランキング上位{top_n}（{now_str}時点）")
    if not pd.isna(progress_rate):
        st.caption(f"📈 進捗率: **{progress_rate*100:.1f}%** | 前日比・5日平均比は終日換算後の値")

    # ── HTMLテーブル ──────────────────────────────────────────
    size_colors = {"超大型":"#FF8C00","大型":"#4CAF50","中型":"#2196F3","ETF等":"#888","":"#888"}
    rows_html = ""
    for i, row in df_top.iterrows():
        s_color  = size_colors.get(row["規模"], "#888")
        vol_str  = f'{int(row["出来高(千株)"]):,}' if not pd.isna(row["出来高(千株)"]) else "-"
        price_str = f'{row["現在値"]:,.0f}' if not pd.isna(row["現在値"]) and row["現在値"] > 0 else "-"
        rows_html += f"""
        <tr>
          <td style="text-align:center;color:#FFD700;font-weight:bold">{i}</td>
          <td style="text-align:left;white-space:nowrap">{row['銘柄名']}</td>
          <td style="text-align:center;color:#CCC">{row['code']}</td>
          <td style="text-align:center;color:{s_color};font-size:0.82em">{row['規模']}</td>
          <td style="text-align:center;color:#99AACC;font-size:0.82em">{row['業種']}</td>
          <td style="text-align:right;font-weight:bold">{row['売買代金(億)']:.0f}</td>
          <td style="text-align:right">{ _color_pct(row.get('前日比(%)'))    if has_daily else '-'}</td>
          <td style="text-align:right">{ _color_pct(row.get('5日平均比(%)')) if has_daily else '-'}</td>
          <td style="text-align:right;color:#AAA;font-size:0.85em">{vol_str}</td>
          <td style="text-align:right;color:#DDD">{price_str}</td>
          <td style="text-align:right">{ _color_pct(row['騰落率(%)'], 2)}</td>
          <td style="text-align:right">{ _color_pct(row.get('20日騰落(%)')) if has_daily else '-'}</td>
          <td style="text-align:right">{ _color_pct(row.get('60日騰落(%)')) if has_daily else '-'}</td>
        </tr>"""

    st.markdown(f"""
    <style>
      .rtable{{width:100%;border-collapse:collapse;font-size:0.88em}}
      .rtable th{{background:#1E2A3A;color:#AAC4E8;padding:7px 9px;text-align:center;
                  border-bottom:2px solid #334;white-space:nowrap}}
      .rtable td{{padding:5px 9px;border-bottom:1px solid #2A3344;color:#E0E0E0}}
      .rtable tr:hover td{{background:#1E2835}}
    </style>
    <table class="rtable"><thead><tr>
      <th>順位</th><th>銘柄名</th><th>コード</th><th>規模</th><th>業種</th>
      <th>売買代金(億)</th><th>前日比*</th><th>5日平均比*</th>
      <th>出来高(千株)</th><th>現在値</th><th>当日騰落</th><th>20日騰落</th><th>60日騰落</th>
    </tr></thead><tbody>{rows_html}</tbody></table>
    <p style="color:#888;font-size:0.78em;margin-top:4px">* 進捗率補正済み（終日換算値で比較）</p>
    """, unsafe_allow_html=True)

    # ── コードコピー ──────────────────────────────────────────
    st.markdown("---")
    top18 = df_top.head(18)["code"].tolist()
    st.markdown("### 📋 上位18銘柄コード（チャートページ用）")
    st.code(",".join(top18), language=None)

    # ── ランキング画像 3分割 ──────────────────────────────────
    st.markdown("---")
    st.markdown("### 🖼 ランキング画像（ダウンロード）")
    date_str = datetime.now(JST).strftime("%Y-%m-%d")

    img_cols = st.columns(3)
    slices = [
        (df_top.iloc[0:20],  "1〜20位",  f"ranking_{date_str}_1-20.png"),
        (df_top.iloc[20:40], "21〜40位", f"ranking_{date_str}_21-40.png"),
        (df_top.iloc[40:60], "41〜60位", f"ranking_{date_str}_41-60.png"),
    ]

    for col, (slice_df, label, fname) in zip(img_cols, slices):
        with col:
            if len(slice_df) == 0:
                st.caption(f"{label}: データなし")
                continue
            # indexを"rank"列として保持してから渡す
            tmp = slice_df.copy()
            tmp["rank"] = tmp.index  # indexが1始まりの順位
            png = build_ranking_image(
                tmp.reset_index(drop=True),
                f"{date_str}　{label}",
                now_str,
                progress_rate,
            )
            st.download_button(
                label=f"💾 {label} PNG保存",
                data=png,
                file_name=fname,
                mime="image/png",
                use_container_width=True,
            )
            # プレビュー
            st.image(png, caption=label, use_container_width=True)

    # ── デバッグ ──────────────────────────────────────────────
    if debug and has_daily:
        with st.expander("🔍 日足計算値確認（上位10件）"):
            dbg = df_top.head(10)[[
                "code","銘柄名","売買代金(億)","前日売買代金(億)",
                "5日平均(億)","前日比(%)","5日平均比(%)","20日騰落(%)","60日騰落(%)"
            ]].round(1)
            st.dataframe(dbg)


# ══════════════════════════════════════════════════════════════
#  メイン実行
# ══════════════════════════════════════════════════════════════
if generate or (auto_refresh and "last_fetch" not in st.session_state):
    with st.spinner(f"📡 {len(CODES)}銘柄スナップショット取得中..."):
        t0 = time.time()
        df_snap = fetch_snapshot(sess, CODES, debug=debug_mode)

    if df_snap is None or df_snap.empty:
        st.error("スナップショット取得失敗。デバッグモードをONにして再試行してください。")
        st.stop()

    st.success(f"✅ スナップショット: {len(df_snap)}銘柄　（{time.time()-t0:.1f}秒）")
    now_str = datetime.now(JST).strftime("%H:%M:%S")

    top_codes_for_daily = df_snap.head(daily_top_n)["code"].tolist()
    with st.spinner(f"📈 上位{daily_top_n}銘柄の日足取得中...（約{daily_top_n//4}秒）"):
        t1 = time.time()
        daily_map = fetch_daily_for_codes(sess, top_codes_for_daily, debug=debug_mode)
    st.success(f"✅ 日足取得完了　（{time.time()-t1:.1f}秒）")

    with st.spinner("🧮 指標計算中..."):
        df_final = calc_metrics(df_snap, daily_map, progress_n=progress_n, debug=debug_mode)

    st.success(f"✅ 全処理完了　{now_str}　合計 {time.time()-t0:.1f}秒")

    st.session_state["ranking_df"]   = df_final
    st.session_state["ranking_time"] = now_str
    st.session_state["last_fetch"]   = time.time()

if "ranking_df" in st.session_state:
    display_ranking(
        st.session_state["ranking_df"], top_n,
        st.session_state.get("ranking_time", ""), debug=debug_mode,
    )

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
