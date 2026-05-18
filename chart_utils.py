"""
chart_utils.py  ―  全ページ共通のデータ取得・描画ロジック
"""
import os, io, warnings, time
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import matplotlib.ticker
import matplotlib.font_manager as fm
import streamlit as st
from datetime import datetime, timedelta, timezone
try:
    import holidays as _holidays
    _JP_HOLIDAYS = _holidays.Japan()
    def _is_jp_holiday(d) -> bool:
        return d in _JP_HOLIDAYS
except ImportError:
    def _is_jp_holiday(d) -> bool:
        return False

JST = timezone(timedelta(hours=9))
from concurrent.futures import ThreadPoolExecutor
warnings.filterwarnings('ignore')

# ── 定数 ────────────────────────────────────────
DPI          = 150
FONT_TITLE   = 12
FONT_TICK    = 8
FONT_LEGEND  = 8

UP_COLOR     = "#E74C3C"
DOWN_COLOR   = "#3498DB"
MA5_COLOR    = "#FF6B35"
MA20_COLOR   = "#4ECDC4"
MA60_COLOR   = "#9B59B6"
BB_COLOR     = "#AAAAAA"
VWAP_COLOR   = "#FFD700"
PREV_HIGH_C  = "#FF4444"
PREV_LOW_C   = "#4488FF"
PREV_CLOSE_C = "#FFAA00"
BG_MAIN      = "#0d0d1a"
BG_AX        = "#1a1a2e"
TC           = "white"

DEFAULT_CODES_18 = [
    "6920","9984","6146","7203","6758",
    "4063","8035","6861","9433","7974",
    "6367","4519","8306","6954","2413",
    "6857","3659","4661",
]

# ── 日本語フォント ───────────────────────────────
FONT_PATH = "/tmp/ipaexg.ttf"
FONT_URL  = "https://moji.or.jp/wp-content/ipafont/IPAexfont/ipaexg00401.zip"

@st.cache_resource
def setup_japanese_font():
    if not os.path.exists(FONT_PATH):
        import zipfile, urllib.request
        urllib.request.urlretrieve(FONT_URL, "/tmp/ipaexg.zip")
        with zipfile.ZipFile("/tmp/ipaexg.zip", "r") as z:
            for name in z.namelist():
                if name.endswith(".ttf"):
                    with open(FONT_PATH, "wb") as f:
                        f.write(z.read(name))
                    break
    prop = fm.FontProperties(fname=FONT_PATH)
    matplotlib.rcParams["font.family"] = prop.get_name()
    fm.fontManager.addfont(FONT_PATH)
    return prop.get_name()

# ── 営業日 ──────────────────────────────────────
def _is_biz_day(d: datetime) -> bool:
    """土日・日本祝日を除外した営業日判定"""
    if d.weekday() >= 5:
        return False
    return not _is_jp_holiday(d.date())

def last_business_days(n=14):
    days, d = [], datetime.now(JST)
    if _is_biz_day(d):
        days.append(d.strftime("%Y-%m-%d"))
    while len(days) < n:
        d -= timedelta(days=1)
        if _is_biz_day(d):
            days.append(d.strftime("%Y-%m-%d"))
    return days  # 新しい順

def today_str():
    return datetime.now(JST).strftime("%Y-%m-%d")

# ── カラム正規化（共通） ─────────────────────────
def normalize_df(df: pd.DataFrame, is_daily=False) -> pd.DataFrame | None:
    cols = df.columns.tolist()
    if is_daily:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.rename(columns={"Date": "DateTime"})
    else:
        if "Date" in cols and "Time" in cols:
            df["DateTime"] = pd.to_datetime(
                df["Date"].astype(str) + " " + df["Time"].astype(str))
        elif "DateTime" in cols:
            df["DateTime"] = pd.to_datetime(df["DateTime"])
        else:
            cl = {c.lower(): c for c in cols}
            if "date" in cl and "time" in cl:
                df["DateTime"] = pd.to_datetime(
                    df[cl["date"]].astype(str) + " " + df[cl["time"]].astype(str))
            elif "datetime" in cl:
                df["DateTime"] = pd.to_datetime(df[cl["datetime"]])
            else:
                return None

    cl = {c.lower(): c for c in df.columns}
    rmap = {}
    for tgt, cands in {
        "open":   ["open","o"],
        "high":   ["high","h"],
        "low":    ["low","l"],
        "close":  ["close","c"],
        "volume": ["volume","vo","v","turnovervalue"],
    }.items():
        for c in cands:
            if c in cl:
                rmap[cl[c]] = tgt
                break
    df = df.rename(columns=rmap)
    for col in ["open","high","low","close","volume"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("DateTime").reset_index(drop=True)

# ── N分足リサンプル ──────────────────────────────
def resample_df(df: pd.DataFrame, n: int, max_bars: int = None) -> pd.DataFrame:
    if n > 1:
        df2 = df.set_index("DateTime").resample(f"{n}min").agg(
            {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
        ).dropna(subset=["open","close"])
        df2 = df2[df2["open"] > 0].reset_index()
    else:
        df2 = df.copy()
    if max_bars:
        df2 = df2.tail(max_bars).reset_index(drop=True)
    return df2

# ── API: 分足取得 ────────────────────────────────
@st.cache_data(ttl=60)
def get_minute_raw(api_key: str, code: str, date_str: str):
    headers = {"x-api-key": api_key}
    params  = {"code": code, "date": date_str}
    rows    = []
    while True:
        r = requests.get(
            "https://api.jquants.com/v2/equities/bars/minute",
            headers=headers, params=params, timeout=15
        )
        if r.status_code != 200:
            return None
        body = r.json()
        rows.extend(body.get("bars") or body.get("data") or [])
        pk = body.get("pagination_key")
        if not pk:
            break
        params["pagination_key"] = pk
    return pd.DataFrame(rows) if rows else None

# ── API: 日足取得 ────────────────────────────────
@st.cache_data(ttl=3600)
def get_daily_raw(api_key: str, code: str, base_date: str = ""):
    if base_date:
        to_dt = datetime.strptime(base_date, "%Y-%m-%d")
    else:
        to_dt = datetime.now(JST).replace(tzinfo=None)
    from_dt   = to_dt - timedelta(weeks=38)
    to_date   = to_dt.strftime("%Y-%m-%d")
    from_date = from_dt.strftime("%Y-%m-%d")
    headers   = {"x-api-key": api_key}
    params    = {"code": code, "from": from_date, "to": to_date}
    r = requests.get(
        "https://api.jquants.com/v2/equities/bars/daily",
        headers=headers, params=params, timeout=15
    )
    if r.status_code != 200:
        return None
    raw = r.json()
    if "data" not in raw or not raw["data"]:
        return None
    return pd.DataFrame(raw["data"])

# ── 1銘柄データパイプライン（分足） ─────────────
def load_intraday(api_key, code, target_date, prev_date, bar_min, max_bars):
    raw = get_minute_raw(api_key, code, target_date)
    if raw is None:
        return None, None
    df = normalize_df(raw)
    if df is None or len(df) == 0:
        return None, None
    df_rs = resample_df(df, bar_min, max_bars)
    if len(df_rs) < 2:
        return None, None
    prev_rs = None
    if prev_date:
        prev_raw = get_minute_raw(api_key, code, prev_date)
        if prev_raw is not None:
            prev_df = normalize_df(prev_raw)
            if prev_df is not None and len(prev_df) > 0:
                prev_rs = resample_df(prev_df, bar_min)
    return df_rs, prev_rs

# ── 1銘柄データパイプライン（日足） ─────────────
def load_daily(api_key, code, base_date=""):
    raw = get_daily_raw(api_key, code, base_date)
    if raw is None:
        return None
    df = normalize_df(raw, is_daily=True)
    if df is None or len(df) < 5:
        return None
    if base_date:
        df = df[df["DateTime"] <= pd.Timestamp(base_date)]
    return df.tail(60).reset_index(drop=True)

# ── 並列取得（分足） ─────────────────────────────
def fetch_all_intraday(api_key, codes, target_date, prev_date, bar_min, max_bars):
    results = {}
    def _load(code):
        return code, load_intraday(api_key, code, target_date, prev_date, bar_min, max_bars)
    with ThreadPoolExecutor(max_workers=min(len(codes), 6)) as exe:
        for code, res in exe.map(_load, codes):
            results[code] = res
    return results

# ── 並列取得（日足） ─────────────────────────────
def fetch_all_daily(api_key, codes, base_date=""):
    results = {}
    def _load(code):
        return code, load_daily(api_key, code, base_date)
    with ThreadPoolExecutor(max_workers=min(len(codes), 6)) as exe:
        for code, df in exe.map(_load, codes):
            results[code] = df
    return results

# ── テクニカル指標（分足・前日補完対応） ──────────
def calc_intraday_indicators(df, prev_df=None):
    df = df.copy()
    if prev_df is not None and len(prev_df) > 0:
        pad = prev_df["close"].iloc[-19:].reset_index(drop=True)
        combined = pd.concat([pad, df["close"].reset_index(drop=True)], ignore_index=True)
        offset = len(pad)
        full_ma10 = combined.rolling(10).mean()
        full_ma20 = combined.rolling(20).mean()
        df["MA10"]  = full_ma10.iloc[offset:].values
        df["MA20"]  = full_ma20.iloc[offset:].values
        df["_ma10_dot"] = pd.array([True]*min(9,  len(df)) + [False]*max(0, len(df)-9))
        df["_ma20_dot"] = pd.array([True]*min(19, len(df)) + [False]*max(0, len(df)-19))
    else:
        df["MA10"]  = df["close"].rolling(10).mean()
        df["MA20"]  = df["close"].rolling(20).mean()
        df["_ma10_dot"] = False
        df["_ma20_dot"] = False

    # VWAP
    denom = df["volume"].cumsum().replace(0, np.nan)
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / denom

    # 出来高MA
    df["vol_ma5"]  = df["volume"].rolling(5).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # RSI(14)
    delta  = df["close"].diff()
    gain   = delta.clip(lower=0)
    loss   = (-delta).clip(lower=0)
    avg_g  = gain.ewm(com=13, min_periods=14).mean()
    avg_l  = loss.ewm(com=13, min_periods=14).mean()
    rs     = avg_g / avg_l.replace(0, np.nan)
    df["RSI14"] = (100 - 100 / (1 + rs)).fillna(50)

    return df

# ── テクニカル指標（日足） ───────────────────────
def calc_daily_indicators(df):
    df = df.copy()
    # MA: 10・20・60（MA5削除、BB削除）
    df["MA10"]  = df["close"].rolling(10).mean()
    df["MA20"]  = df["close"].rolling(20).mean()
    df["MA60"]  = df["close"].rolling(60).mean()

    # VWAP（累積）
    denom = df["volume"].cumsum().replace(0, np.nan)
    df["VWAP"] = (df["close"] * df["volume"]).cumsum() / denom

    # 出来高MA20
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # RSI(14)
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=13, min_periods=14).mean()
    avg_l = loss.ewm(com=13, min_periods=14).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    df["RSI14"] = (100 - 100 / (1 + rs)).fillna(50)

    # MA20乖離率
    df["ma20_dev"] = (df["close"] - df["MA20"]) / df["MA20"] * 100

    return df

# ── ローソク足 ───────────────────────────────────
def draw_candles(df, ax):
    for i, row in df.iterrows():
        color = UP_COLOR if row["close"] >= row["open"] else DOWN_COLOR
        ax.plot([i, i], [row["low"], row["high"]], color=color, lw=0.8, zorder=2)
        bh = max(abs(row["close"] - row["open"]), row["close"] * 0.001)
        ax.add_patch(mpatches.Rectangle(
            (i - 0.35, min(row["open"], row["close"])),
            0.7, bh, linewidth=0, facecolor=color, zorder=3))

# ── MAを実線/点線で分割描画 ─────────────────────
def plot_ma_split(ax, idx, series, dot_mask, color, lw, label):
    plotted = False
    i = 0
    while i < len(series):
        is_dot = bool(dot_mask.iloc[i]) if i < len(dot_mask) else False
        j = i
        while j < len(series) and (bool(dot_mask.iloc[j]) if j < len(dot_mask) else False) == is_dot:
            j += 1
        seg_idx = idx[i:j]
        seg_val = series.iloc[i:j]
        if i > 0:
            seg_idx = np.concatenate([[idx[i-1]], seg_idx])
            seg_val = pd.concat([series.iloc[i-1:i], seg_val])
        lbl = label if not plotted else "_nolegend_"
        ax.plot(seg_idx, seg_val, color=color, lw=lw,
                linestyle=":" if is_dot else "-",
                alpha=0.6 if is_dot else 1.0, label=lbl, zorder=4)
        plotted = True
        i = j

# ── 凡例整形（共通） ─────────────────────────────
def arrange_legend(ax, prev_high, prev_low, prev_close):
    handles, labels = ax.get_legend_handles_labels()
    if "VWAP" in labels:
        vi = labels.index("VWAP")
        handles = [handles[vi]] + [h for j,h in enumerate(handles) if j!=vi]
        labels  = [labels[vi]]  + [l for j,l in enumerate(labels)  if j!=vi]
    if prev_high is not None:
        blank = mpatches.Patch(color="none")
        handles += [blank, blank, blank]
        labels  += [
            f"前日高値 {prev_high:.0f}",
            f"前日安値 {prev_low:.0f}",
            f"前日終値 {prev_close:.0f}",
        ]
    ax.legend(handles, labels, fontsize=FONT_LEGEND, loc="upper left",
              facecolor="#1a1a2e", edgecolor="#555555",
              labelcolor=TC, framealpha=0.90, ncol=2, handlelength=1.8)

# ── 凡例整形（分足専用・右上） ───────────────────
def arrange_legend_intraday(ax, prev_high, prev_low, prev_close,
                             day_high, day_low, vwap_dev):
    handles, labels = ax.get_legend_handles_labels()
    # VWAPを先頭に
    if "VWAP" in labels:
        vi = labels.index("VWAP")
        handles = [handles[vi]] + [h for j,h in enumerate(handles) if j!=vi]
        labels  = [labels[vi]]  + [l for j,l in enumerate(labels)  if j!=vi]
    blank = mpatches.Patch(color="none")
    # 当日高値・安値
    handles += [
        mpatches.Patch(color="#FF88AA"),
        mpatches.Patch(color="#88CCFF"),
    ]
    labels += [
        f"当日高値 {day_high:.0f}",
        f"当日安値 {day_low:.0f}",
    ]
    # 前日データ
    if prev_high is not None:
        handles += [blank, blank, blank]
        labels  += [
            f"前日高値 {prev_high:.0f}",
            f"前日安値 {prev_low:.0f}",
            f"前日終値 {prev_close:.0f}",
        ]
    ax.legend(handles, labels, fontsize=FONT_LEGEND, loc="upper right",
              facecolor="#1a1a2e", edgecolor="#555555",
              labelcolor=TC, framealpha=0.90, ncol=2, handlelength=1.5)

# ── 軸スタイル適用 ───────────────────────────────
def style_ax(ax, xticks=None, xlabels=None):
    ax.set_facecolor(BG_AX)
    ax.tick_params(colors=TC, labelsize=FONT_TICK)
    for sp in ax.spines.values():
        sp.set_color("#444444")
    if xticks is not None:
        ax.set_xticks(xticks)
        ax.set_xticklabels(xlabels, rotation=45, ha="right",
                           color=TC, fontsize=FONT_TICK)

# ── 1銘柄 分足チャート描画 ───────────────────────
def plot_intraday_stock(df, code, prev_rs, bar_min, ax_p, ax_v, ax_rsi, date_label):
    df  = calc_intraday_indicators(df, prev_rs)
    n   = len(df)
    idx = np.arange(n)

    # ── 前日データ ───────────────────────────────
    prev_high = prev_low = prev_close = None
    if prev_rs is not None and len(prev_rs) > 0:
        prev_high  = prev_rs["high"].max()
        prev_low   = prev_rs["low"].min()
        prev_close = prev_rs["close"].iloc[-1]

    # ── 当日高値・安値 ───────────────────────────
    day_high  = df["high"].max()
    day_low   = df["low"].min()

    # ── VWAP乖離率（最終バー） ───────────────────
    last_close = df["close"].iloc[-1]
    last_vwap  = df["VWAP"].iloc[-1]
    vwap_dev   = (last_close - last_vwap) / last_vwap * 100 if last_vwap and last_vwap != 0 else 0

    # ── 出来高増加率（直近5本/20本平均） ─────────
    vol_recent5  = df["volume"].iloc[-5:].mean() if n >= 5  else df["volume"].mean()
    vol_ma20_val = df["vol_ma20"].iloc[-1] if not pd.isna(df["vol_ma20"].iloc[-1]) else vol_recent5
    vol_ratio    = vol_recent5 / vol_ma20_val * 100 if vol_ma20_val > 0 else 100

    # ── ローソク足・MA・VWAP ─────────────────────
    draw_candles(df, ax_p)
    plot_ma_split(ax_p, idx, df["MA10"], df["_ma10_dot"], MA5_COLOR,  1.2, "MA10")
    plot_ma_split(ax_p, idx, df["MA20"], df["_ma20_dot"], MA20_COLOR, 1.2, "MA20")
    ax_p.plot(idx, df["VWAP"], color=VWAP_COLOR, lw=3.5, alpha=0.95, label="VWAP", zorder=5)

    # ── 当日高値・安値 水平線 ────────────────────
    ax_p.axhline(day_high, color="#FF88AA", lw=0.9, linestyle="--", zorder=4)
    ax_p.axhline(day_low,  color="#88CCFF", lw=0.9, linestyle="--", zorder=4)

    # ── タイトル（更新時刻・VWAP乖離率・出来高増加率） ─
    bar_lbl    = f"{bar_min}分足" if bar_min > 1 else "1分足"
    update_hm  = datetime.now(JST).strftime("%H:%M")
    dev_sign   = "+" if vwap_dev >= 0 else ""
    vr_sign    = "+" if vol_ratio >= 100 else ""
    title_str  = (f"{code}  {date_label}  {bar_lbl}  "
                  f"[{update_hm}更新]  "
                  f"VWAP乖離:{dev_sign}{vwap_dev:.1f}%  "
                  f"出来高比:{vr_sign}{vol_ratio-100:.0f}%")
    ax_p.set_title(title_str, color=TC, fontsize=FONT_TITLE - 1,
                   fontweight="bold", pad=4)

    style_ax(ax_p)
    ax_p.set_xticks([])
    ax_p.yaxis.set_label_position("right")
    ax_p.yaxis.tick_right()
    ax_p.tick_params(axis="y", colors=TC, labelsize=FONT_TICK)

    # ── 凡例（右上・前日＋当日高安値） ───────────
    arrange_legend_intraday(ax_p, prev_high, prev_low, prev_close, day_high, day_low, vwap_dev)

    # ── 14:30のインデックスを特定 ─────────────────
    cutoff_idx = None
    for i, row in df.iterrows():
        t = row["DateTime"]
        if hasattr(t, "hour") and (t.hour > 14 or (t.hour == 14 and t.minute >= 30)):
            cutoff_idx = i
            break

    # ── 出来高バー（③色分け：直近5本MA > 20本MA → 赤系、< → 青系） ─
    bar_colors  = []
    bar_alphas  = []
    bar_edges   = []
    bar_elw     = []
    for i in range(n):
        ma5_v  = df["vol_ma5"].iloc[i]
        ma20_v = df["vol_ma20"].iloc[i]
        after_cutoff = (cutoff_idx is not None and i >= cutoff_idx)
        if pd.isna(ma5_v) or pd.isna(ma20_v):
            bar_colors.append(UP_COLOR)
        elif ma5_v >= ma20_v:
            bar_colors.append("#CC2222")   # 濃い赤（上昇勢い）
        else:
            bar_colors.append("#5588AA")   # 青グレー（勢い弱）
        bar_alphas.append(0.95 if after_cutoff else 0.70)
        bar_edges.append("#FFD700" if after_cutoff else "none")
        bar_elw.append(0.8 if after_cutoff else 0.0)

    for i in range(n):
        ax_v.bar(i, df["volume"].iloc[i],
                 color=bar_colors[i], alpha=bar_alphas[i],
                 edgecolor=bar_edges[i], linewidth=bar_elw[i], zorder=3)

    # ── 14:30 区切り縦線 ──────────────────────────
    if cutoff_idx is not None:
        ax_v.axvline(cutoff_idx - 0.5, color="#FFD700", lw=1.2,
                     linestyle="--", zorder=5, label="14:30→")
        ax_p.axvline(cutoff_idx - 0.5, color="#FFD700", lw=0.8,
                     linestyle="--", alpha=0.5, zorder=4)

    # ── 出来高MA5・MA20折れ線 ─────────────────────
    ax_v.plot(idx, df["vol_ma5"],  color="#FFAA44", lw=1.2, label="出来高MA5",  zorder=4)
    ax_v.plot(idx, df["vol_ma20"], color="#AAAAFF", lw=1.2, label="出来高MA20", zorder=4)

    step = max(1, n // 6)
    style_ax(ax_v,
             xticks=idx[::step],
             xlabels=df["DateTime"].dt.strftime("%H:%M").iloc[::step].tolist())
    ax_v.set_ylabel("")
    ax_v.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
    ax_v.tick_params(axis="y", colors=TC, labelsize=FONT_TICK)
    ax_v.legend(fontsize=6, loc="upper left", facecolor="#1a1a2e",
                edgecolor="#555555", labelcolor=TC, framealpha=0.80)

    # ── RSIパネル ────────────────────────────────
    rsi_vals = df["RSI14"].values
    ax_rsi.plot(idx, rsi_vals, color="#BB88FF", lw=1.2, zorder=4)
    ax_rsi.axhline(70, color="#FF6666", lw=0.7, linestyle="--", alpha=0.8)
    ax_rsi.axhline(50, color="#888888", lw=0.6, linestyle=":",  alpha=0.6)
    ax_rsi.axhline(30, color="#66AAFF", lw=0.7, linestyle="--", alpha=0.8)
    ax_rsi.fill_between(idx, rsi_vals, 70,
                         where=(rsi_vals >= 70), interpolate=True,
                         color="#FF6666", alpha=0.20)
    ax_rsi.fill_between(idx, rsi_vals, 30,
                         where=(rsi_vals <= 30), interpolate=True,
                         color="#66AAFF", alpha=0.20)
    if cutoff_idx is not None:
        ax_rsi.axvline(cutoff_idx - 0.5, color="#FFD700", lw=0.8,
                       linestyle="--", alpha=0.5, zorder=4)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.set_yticks([30, 50, 70])
    style_ax(ax_rsi, xticks=idx[::step],
             xlabels=df["DateTime"].dt.strftime("%H:%M").iloc[::step].tolist())
    ax_rsi.tick_params(axis="y", colors=TC, labelsize=6)
    ax_rsi.yaxis.set_label_position("right")
    ax_rsi.yaxis.tick_right()
    ax_rsi.text(0.005, 0.80, "RSI(14)", transform=ax_rsi.transAxes,
                fontsize=6, color="#BB88FF", va="top")

# ── 日足：凡例整形（右上） ───────────────────────
def arrange_legend_daily(ax, prev_high, prev_low, prev_close,
                          vwap_dev, ma20_dev, recent_high=None, recent_low=None):
    handles, labels = ax.get_legend_handles_labels()
    if "VWAP" in labels:
        vi = labels.index("VWAP")
        handles = [handles[vi]] + [h for j, h in enumerate(handles) if j != vi]
        labels  = [labels[vi]]  + [l for j, l in enumerate(labels)  if j != vi]
    blank = mpatches.Patch(color="none")
    if recent_high is not None:
        handles += [mpatches.Patch(color="#FF88AA"), mpatches.Patch(color="#88CCFF")]
        labels  += [f"── 20日高値 {recent_high:.0f}", f"── 20日安値 {recent_low:.0f}"]
    if prev_close is not None:
        handles += [mpatches.Patch(color="#FFAA00")]
        labels  += [f"前日終値 {prev_close:.0f}"]
    if prev_high is not None:
        handles += [blank, blank]
        labels  += [f"前日高値 {prev_high:.0f}", f"前日安値 {prev_low:.0f}"]
    ax.legend(handles, labels, fontsize=FONT_LEGEND, loc="upper right",
              facecolor="#1a1a2e", edgecolor="#555555",
              labelcolor=TC, framealpha=0.90, ncol=2, handlelength=1.5)

# ── 1銘柄 日足チャート描画 ───────────────────────
def plot_daily_stock(df, code, ax_p, ax_v, ax_rsi, date_label=""):
    df  = calc_daily_indicators(df)
    n   = len(df)
    idx = np.arange(n)

    last_close = df["close"].iloc[-1]

    # ── 前日データ ───────────────────────────────
    prev_high = prev_low = prev_close = None
    if n >= 2:
        prev = df.iloc[-2]
        prev_high, prev_low, prev_close = prev["high"], prev["low"], prev["close"]

    # ── 各種指標計算 ─────────────────────────────
    last_vwap = df["VWAP"].iloc[-1]
    vwap_dev  = (last_close - last_vwap) / last_vwap * 100 if last_vwap and last_vwap != 0 else 0
    ma20_dev  = df["ma20_dev"].iloc[-1] if not pd.isna(df["ma20_dev"].iloc[-1]) else 0
    day_chg   = (last_close - prev_close) / prev_close * 100 if prev_close and prev_close != 0 else 0

    # ── 直近20日高値・安値・終値位置 ─────────────
    window_20   = min(20, n)
    recent_high = df["high"].iloc[-window_20:].max()
    recent_low  = df["low"].iloc[-window_20:].min()
    price_range = recent_high - recent_low
    pos_pct     = (last_close - recent_low) / price_range * 100 if price_range > 0 else 50.0
    if pos_pct <= 20:   pos_label = "安値圏"
    elif pos_pct <= 40: pos_label = "下段"
    elif pos_pct <= 60: pos_label = "中段"
    elif pos_pct <= 80: pos_label = "高値圏"
    else:               pos_label = "高値更新圏"

    # ── MA・トレンド判定 ──────────────────────────
    last_ma10  = df["MA10"].iloc[-1]
    last_ma20  = df["MA20"].iloc[-1]
    last_ma60  = df["MA60"].iloc[-1]
    ma20_slope = df["MA20"].iloc[-1] - df["MA20"].iloc[-4] if n >= 4 else 0
    ma20_up    = ma20_slope > 0
    valid_mas  = not (pd.isna(last_ma20) or pd.isna(last_ma60))

    if valid_mas and last_close > last_ma20 and ma20_up:
        trend_txt, trend_color = "上昇継続　↑", "#44FF88"
    elif valid_mas and last_close < last_ma20 and not ma20_up:
        trend_txt, trend_color = "下降継続　↓", "#FF4444"
    else:
        trend_txt, trend_color = "横ばい", "#FFD700"

    if valid_mas and not pd.isna(last_ma10):
        if last_close > last_ma10 > last_ma20 > last_ma60:
            ma_pos_txt = "株価>MA10>MA20>MA60"
        elif last_close > last_ma20 > last_ma10:
            ma_pos_txt = "株価>MA20>MA10"
        elif last_close > last_ma20:
            ma_pos_txt = "株価>MA20"
        elif last_close < last_ma10 < last_ma20 < last_ma60:
            ma_pos_txt = "株価<MA10<MA20<MA60"
        elif last_close < last_ma20:
            ma_pos_txt = "株価<MA20"
        else:
            ma_pos_txt = "MA混在"
    else:
        ma_pos_txt = ""

    # ── ローソク足描画 ────────────────────────────
    for i, row in df.iterrows():
        is_last = (i == n - 1)
        color   = UP_COLOR if row["close"] >= row["open"] else DOWN_COLOR
        ax_p.plot([i, i], [row["low"], row["high"]], color=color,
                  lw=1.5 if is_last else 0.8, zorder=2)
        bh = max(abs(row["close"] - row["open"]), row["close"] * 0.001)
        if is_last:
            ax_p.add_patch(mpatches.Rectangle(
                (i - 0.42, min(row["open"], row["close"])),
                0.84, bh, linewidth=0, facecolor=color, zorder=4))
            ax_p.add_patch(mpatches.Rectangle(
                (i - 0.50, row["low"]),
                1.0, row["high"] - row["low"],
                linewidth=0, facecolor="#FFD700", alpha=0.10, zorder=1))
        else:
            ax_p.add_patch(mpatches.Rectangle(
                (i - 0.35, min(row["open"], row["close"])),
                0.7, bh, linewidth=0, facecolor=color, zorder=3))

    # ── MA・VWAP ─────────────────────────────────
    MA10_COLOR = "#FF9933"
    ax_p.plot(idx, df["MA10"], color=MA10_COLOR, lw=1.0, label="MA10", zorder=4)
    ax_p.plot(idx, df["MA20"], color=MA20_COLOR, lw=1.0, label="MA20", zorder=4)
    ax_p.plot(idx, df["MA60"], color=MA60_COLOR, lw=1.0, label="MA60", zorder=4)
    ax_p.plot(idx, df["VWAP"], color=VWAP_COLOR, lw=3.5, alpha=0.95, label="VWAP", zorder=5)

    # ── 前日終値ライン ────────────────────────────
    if prev_close is not None:
        ax_p.axhline(prev_close, color="#FFAA00", lw=0.9, linestyle=":", alpha=0.85, zorder=4)

    # ── 20日高値・安値の水平線 ────────────────────
    ax_p.axhline(recent_high, color="#FF88AA", lw=0.9, linestyle="--", alpha=0.85, zorder=4)
    ax_p.axhline(recent_low,  color="#88CCFF", lw=0.9, linestyle="--", alpha=0.85, zorder=4)

    # ── スタイル適用 ─────────────────────────────
    style_ax(ax_p)
    ax_p.set_xticks([])
    ax_p.yaxis.set_label_position("right")
    ax_p.yaxis.tick_right()
    ax_p.tick_params(axis="y", colors=TC, labelsize=FONT_TICK)

    # ── タイトル3行（ax.text + transAxes で確実に中央） ─
    update_hm = datetime.now(JST).strftime("%H:%M")
    date_str  = df["DateTime"].iloc[-1].strftime("%Y-%m-%d") if date_label == "" else date_label
    chg_sign  = "+" if day_chg >= 0 else ""
    dev_sign  = "+" if vwap_dev >= 0 else ""
    ma20_sign = "+" if ma20_dev >= 0 else ""

    # 1行目：コード・日付・更新時刻（左揃え）
    ax_p.text(0.0, 1.13, f"{code}  {date_str}  日足  [{update_hm}更新]",
              transform=ax_p.transAxes,
              fontsize=FONT_TITLE - 1, fontweight="bold",
              color=TC, ha="left", va="bottom", clip_on=False)

    # 2行目：トレンド＋MA位置（中央揃え）
    line2 = f"{trend_txt}　｜　{ma_pos_txt}" if ma_pos_txt else trend_txt
    ax_p.text(0.5, 1.075, line2,
              transform=ax_p.transAxes,
              fontsize=FONT_TITLE - 1.5, fontweight="bold",
              color=trend_color, ha="center", va="bottom", clip_on=False)

    # 3行目：数値情報（中央揃え）
    line3 = (f"20日位置:{pos_pct:.0f}% {pos_label}   "
             f"当日:{chg_sign}{day_chg:.1f}%   "
             f"VWAP乖離:{dev_sign}{vwap_dev:.1f}%   "
             f"MA20乖離:{ma20_sign}{ma20_dev:.1f}%")
    ax_p.text(0.5, 1.025, line3,
              transform=ax_p.transAxes,
              fontsize=FONT_TITLE - 2.5,
              color="#CCCCCC", ha="center", va="bottom", clip_on=False)

    arrange_legend_daily(ax_p, prev_high, prev_low, prev_close,
                         vwap_dev, ma20_dev, recent_high, recent_low)

    # ── 出来高バー ───────────────────────────────
    for i in range(n):
        is_up     = df["close"].iloc[i] >= df["open"].iloc[i]
        is_recent = (i >= n - 5)
        ax_v.bar(i, df["volume"].iloc[i],
                 color=UP_COLOR if is_up else DOWN_COLOR,
                 alpha=0.95 if is_recent else 0.60, zorder=3)

    ax_v.plot(idx, df["vol_ma20"], color="#AAAAFF", lw=1.2, label="出来高MA20", zorder=4)

    step = max(1, n // 6)
    style_ax(ax_v,
             xticks=idx[::step],
             xlabels=df["DateTime"].dt.strftime("%m/%d").iloc[::step].tolist())
    ax_v.set_ylabel("")
    ax_v.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda x, _: f"{x/10000:.0f}万"))
    ax_v.tick_params(axis="y", colors=TC, labelsize=FONT_TICK)
    ax_v.legend(fontsize=6, loc="upper left", facecolor="#1a1a2e",
                edgecolor="#555555", labelcolor=TC, framealpha=0.80)

    # ── RSIパネル ────────────────────────────────
    rsi_vals = df["RSI14"].values
    ax_rsi.plot(idx, rsi_vals, color="#BB88FF", lw=1.2, zorder=4)
    ax_rsi.axhline(70, color="#FF6666", lw=0.7, linestyle="--", alpha=0.8)
    ax_rsi.axhline(50, color="#888888", lw=0.6, linestyle=":",  alpha=0.6)
    ax_rsi.axhline(30, color="#66AAFF", lw=0.7, linestyle="--", alpha=0.8)
    ax_rsi.fill_between(idx, rsi_vals, 70, where=(rsi_vals >= 70),
                        interpolate=True, color="#FF6666", alpha=0.20)
    ax_rsi.fill_between(idx, rsi_vals, 30, where=(rsi_vals <= 30),
                        interpolate=True, color="#66AAFF", alpha=0.20)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.set_yticks([30, 50, 70])
    style_ax(ax_rsi, xticks=idx[::step],
             xlabels=df["DateTime"].dt.strftime("%m/%d").iloc[::step].tolist())
    ax_rsi.tick_params(axis="y", colors=TC, labelsize=6)
    ax_rsi.yaxis.set_label_position("right")
    ax_rsi.yaxis.tick_right()
    ax_rsi.text(0.005, 0.80, "RSI(14)", transform=ax_rsi.transAxes,
                fontsize=6, color="#BB88FF", va="top")

# ── 6銘柄（3列×2行）→ 1 figure ──────────────────
def build_figure_6(group6, data_map, mode, bar_min=5, date_label=""):
    """
    mode: "intraday" or "daily"
    data_map: code → (df, prev_rs) for intraday / code → df for daily
    """
    COLS, ROWS = 3, 2
    # 分足・日足ともに高さ比率 5:1.2:1（ローソク:出来高:RSI）
    cell_h_ratios = [5, 1.2, 1]
    n_inner = 3
    fig_row_h = 10

    fig = plt.figure(figsize=(COLS * 6.5, ROWS * fig_row_h), dpi=DPI, facecolor=BG_MAIN)
    outer = gridspec.GridSpec(ROWS, COLS, figure=fig, wspace=0.30, hspace=0.38)

    for idx, code in enumerate(group6):
        ri, ci = divmod(idx, COLS)
        inner = gridspec.GridSpecFromSubplotSpec(
            n_inner, 1, subplot_spec=outer[ri, ci],
            height_ratios=cell_h_ratios, hspace=0.06)
        ax_p   = fig.add_subplot(inner[0])
        ax_v   = fig.add_subplot(inner[1])
        ax_rsi = fig.add_subplot(inner[2])

        if mode == "intraday":
            df, prev = data_map.get(code, (None, None))
            if df is not None:
                plot_intraday_stock(df, code, prev, bar_min, ax_p, ax_v, ax_rsi, date_label)
            else:
                _empty_cell(ax_p, ax_v, code, ax_rsi)
        else:
            df = data_map.get(code)
            if df is not None:
                plot_daily_stock(df, code, ax_p, ax_v, ax_rsi, date_label)
            else:
                _empty_cell(ax_p, ax_v, code, ax_rsi)

    # 空きセル非表示
    for idx in range(len(group6), ROWS * COLS):
        ri, ci = divmod(idx, COLS)
        inner = gridspec.GridSpecFromSubplotSpec(
            n_inner, 1, subplot_spec=outer[ri, ci],
            height_ratios=cell_h_ratios, hspace=0.06)
        for sp in range(n_inner):
            fig.add_subplot(inner[sp]).set_visible(False)
    return fig

def _empty_cell(ax_p, ax_v, code, ax_rsi=None):
    axes = [ax_p, ax_v]
    if ax_rsi is not None:
        axes.append(ax_rsi)
    for ax in axes:
        ax.set_facecolor(BG_AX)
        ax.tick_params(colors=TC)
        for sp in ax.spines.values():
            sp.set_color("#444444")
    ax_p.text(0.5, 0.5, f"{code}\nデータなし",
              ha="center", va="center", color=TC,
              fontsize=FONT_TITLE, transform=ax_p.transAxes)
    ax_p.set_title(code, color=TC, fontsize=FONT_TITLE, fontweight="bold", pad=4)

# ── 銘柄入力UI（共通） ───────────────────────────
def codes_input_ui(session_key: str, default_codes: list) -> list:
    if session_key not in st.session_state:
        st.session_state[session_key] = ",".join(default_codes)
    val = st.text_input(
        "銘柄コード（カンマ区切り・最大18銘柄）",
        value=st.session_state[session_key],
        key=f"{session_key}_input"
    )
    if val != st.session_state[session_key]:
        st.session_state[session_key] = val
    return [c.strip() for c in val.split(",") if c.strip()][:18]

# ── チャート生成・表示（共通UI） ─────────────────
def render_charts(figures):
    """figuresのリストを受け取り表示（タップで保存可能）"""
    st.caption("📲 画像を長押し（iPhone）またはタップして保存できます")
    for gi, (fname, png, group6) in enumerate(figures):
        st.markdown(f"**画像{gi+1}：{' / '.join(group6)}**")
        st.image(png, use_container_width=True)

# ── PNG生成 ──────────────────────────────────────
def fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight", facecolor=BG_MAIN)
    buf.seek(0)
    return buf.read()


# ════════════════════════════════════════════════════════════════════════════
# ▼▼▼  売買代金ランキング機能（ページ5・6用）  ▼▼▼
# ════════════════════════════════════════════════════════════════════════════

RK_BG      = "#0d0d1a"
RK_PANEL   = "#12122a"
RK_HEADER  = "#1e1e42"
RK_ACCENT  = "#e94560"
RK_ACCENT2 = "#4ecdc4"
RK_TEXT    = "#e8e8f0"
RK_SUB     = "#8888aa"
RK_POS     = "#ff6b6b"
RK_NEG     = "#4ecdc4"
RK_BORDER  = "#2a2a4a"
RK_GOLD    = "#ffd700"
RK_SILVER  = "#c0c0c0"
RK_BRONZE  = "#cd7f32"
RK_SCORE_H = "#ff6b35"
RK_SCORE_L = "#4ecdc4"


def _trim_code(code) -> str:
    """5桁→4桁: 末尾の0を1文字だけ削除 (69200→6920, 13010→1301)"""
    s = str(code).strip()
    if len(s) == 5 and s.endswith("0"):
        return s[:-1]
    return s


def _scale_label(scale_cat: str) -> str:
    """ScaleCat → 超大型/大型/中型/小型/-"""
    if not isinstance(scale_cat, str) or scale_cat.strip() == "-" or scale_cat.strip() == "":
        return "-"
    s = scale_cat.upper()
    if "CORE" in s or "30" in s:
        return "超大型"
    if "LARGE" in s or "70" in s:
        return "大型"
    if "MID" in s or "400" in s:
        return "中型"
    if "SMALL" in s:
        return "小型"
    return "-"


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_day(api_key: str, date_str: str) -> pd.DataFrame:
    headers  = {"x-api-key": api_key}
    params   = {"date": date_str}
    all_rows = []
    while True:
        r = requests.get(
            "https://api.jquants.com/v2/equities/bars/daily",
            headers=headers, params=params, timeout=30,
        )
        if r.status_code != 200:
            return pd.DataFrame()
        body = r.json()
        rows = body.get("daily_quotes", body.get("items", body.get("data", [])))
        all_rows.extend(rows)
        pk = body.get("pagination_key")
        if not pk:
            break
        params["pagination_key"] = pk
    if not all_rows:
        return pd.DataFrame()
    df = pd.DataFrame(all_rows)
    df = df.rename(columns={"Date":"date","Code":"code","C":"close","Vo":"volume","Va":"turnover"})
    df["code"]     = df["code"].astype(str).apply(_trim_code)
    df["date"]     = pd.to_datetime(df["date"])
    df["close"]    = pd.to_numeric(df["close"],    errors="coerce")
    df["volume"]   = pd.to_numeric(df["volume"],   errors="coerce")
    df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce")
    return df[["date","code","close","volume","turnover"]].dropna(subset=["code"])


@st.cache_data(ttl=86400, show_spinner=False)
def _get_listed_info_v2(api_key: str) -> pd.DataFrame:
    headers = {"x-api-key": api_key}
    r = requests.get(
        "https://api.jquants.com/v2/equities/master",
        headers=headers, timeout=30,
    )
    if r.status_code != 200:
        return pd.DataFrame()
    body = r.json()
    rows = body.get("data", body.get("items", body.get("info", [])))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["Code"] = df["Code"].astype(str).apply(_trim_code)
    df = df.rename(columns={"Code": "code", "CoName": "name", "S17Nm": "sector"})
    # ScaleCat → 規模区分
    if "ScaleCat" in df.columns:
        df["scale"] = df["ScaleCat"].apply(_scale_label)
    else:
        df["scale"] = "-"
    keep = [c for c in ["code", "name", "sector", "scale"] if c in df.columns]
    return df[keep].set_index("code")


def _biz_date_before(target: str, n: int) -> str:
    d = datetime.strptime(target, "%Y-%m-%d")
    skipped = 0
    while skipped < n:
        d -= timedelta(days=1)
        if _is_biz_day(d):
            skipped += 1
    return d.strftime("%Y-%m-%d")


def _score_step(val, pos_breaks, neg_breaks):
    try:
        v = float(val)
        if np.isnan(v): return 0
    except:
        return 0
    if v > 0:
        for threshold, pts in pos_breaks:
            if v >= threshold: return pts
    elif v < 0:
        for threshold, pts in neg_breaks:
            if v <= threshold: return pts
    return 0

def calc_score(row) -> int:
    score = 0
    score += _score_step(row.get("売買代金前日比(補正%)", 0),
        [(150,25),(100,21),(70,17),(40,12),(20,6)],
        [(-150,-25),(-100,-21),(-70,-17),(-40,-12),(-20,-6)])
    score += _score_step(row.get("5日平均比(補正%)", 0),
        [(120,20),(90,16),(60,12),(40,9),(20,5)],
        [(-120,-20),(-90,-16),(-60,-12),(-40,-9),(-20,-5)])
    score += _score_step(row.get("出来高前日比(補正%)", 0),
        [(80,15),(60,12),(40,8),(20,4)],
        [(-80,-15),(-60,-12),(-40,-8),(-20,-4)])
    score += _score_step(row.get("出来高5日平均比(補正%)", 0),
        [(80,10),(60,8),(40,6),(20,3)],
        [(-80,-10),(-60,-8),(-40,-6),(-20,-3)])
    score += _score_step(row.get("当日騰落率(%)", 0),
        [(6,11),(3,8),(1,5)],
        [(-6,-11),(-3,-8),(-1,-5)])
    score += _score_step(row.get("20日騰落率(%)", 0),
        [(35,10),(18,7),(8,4)],
        [(-35,-10),(-18,-7),(-8,-4)])
    score += _score_step(row.get("60日騰落率(%)", 0),
        [(45,9),(25,6),(12,3)],
        [(-45,-9),(-25,-6),(-12,-3)])
    return int(score)


def fetch_ranking_data(api_key: str, target_date: str, top_n: int = 60) -> tuple:
    d_target = target_date
    d_prev   = _biz_date_before(target_date, 1)
    d_20     = _biz_date_before(target_date, 20)
    d_60     = _biz_date_before(target_date, 60)
    d_5days  = [_biz_date_before(target_date, i) for i in range(1, 6)]
    fetch_dates = list(dict.fromkeys([d_target, d_prev, d_20, d_60] + d_5days))

    frames = {}
    def _load(d):
        return d, _fetch_day(api_key, d)
    with ThreadPoolExecutor(max_workers=8) as exe:
        for d, df in exe.map(_load, fetch_dates):
            frames[d] = df

    df_target = frames.get(d_target, pd.DataFrame())
    if df_target.empty:
        return pd.DataFrame(), 1.0

    today_df = (
        df_target.dropna(subset=["turnover"])
        .nlargest(top_n, "turnover")
        .reset_index(drop=True)
    )
    if today_df.empty:
        return pd.DataFrame(), 1.0

    codes_top = today_df["code"].tolist()

    def _col(d, col):
        df = frames.get(d, pd.DataFrame())
        if df.empty:
            return pd.Series(dtype=float)
        sub = df[df["code"].isin(codes_top)].set_index("code")
        return sub[col] if col in sub.columns else pd.Series(dtype=float)

    today_top30 = _col(d_target, "turnover").reindex(codes_top[:30]).sum()
    prev_top30  = _col(d_prev,   "turnover").reindex(codes_top[:30]).sum()
    progress_rate = max(0.01, min(today_top30 / prev_top30, 1.5)) if prev_top30 > 0 and today_top30 > 0 else 1.0

    today_close    = _col(d_target, "close")
    prev_close     = _col(d_prev,   "close")
    close_20       = _col(d_20,     "close")
    close_60       = _col(d_60,     "close")
    today_turnover = _col(d_target, "turnover")
    prev_turnover  = _col(d_prev,   "turnover")
    today_volume   = _col(d_target, "volume")
    prev_volume    = _col(d_prev,   "volume")
    turnover_5d    = pd.concat([_col(d, "turnover") for d in d_5days], axis=1).mean(axis=1)
    volume_5d      = pd.concat([_col(d, "volume")   for d in d_5days], axis=1).mean(axis=1)

    adj_turnover = today_turnover / progress_rate
    adj_volume   = today_volume   / progress_rate

    base = today_df.set_index("code")
    df   = pd.DataFrame(index=base.index)

    def pct(a, b):
        return ((a - b) / b * 100).round(0)

    df["売買代金(億円)"]        = (base["turnover"] / 1e8).round(0).astype(int)
    df["出来高(千株)"]          = (base["volume"]   / 1e3).round(0).astype(int)
    df["売買代金前日比(補正%)"]  = pct(adj_turnover, prev_turnover)
    df["5日平均比(補正%)"]       = pct(adj_turnover, turnover_5d)
    df["出来高前日比(補正%)"]    = pct(adj_volume,   prev_volume)
    df["出来高5日平均比(補正%)"] = pct(adj_volume,   volume_5d)
    df["当日騰落率(%)"]          = pct(today_close,  prev_close)
    df["20日騰落率(%)"]          = pct(today_close,  close_20)
    df["60日騰落率(%)"]          = pct(today_close,  close_60)

    listed = _get_listed_info_v2(api_key)
    if not listed.empty:
        reindexed   = listed.reindex(df.index)
        df["業種"]   = reindexed["sector"].fillna("-").astype(str) if "sector" in reindexed.columns else "-"
        df["規模"]   = reindexed["scale"].fillna("-").astype(str)  if "scale"  in reindexed.columns else "-"
        df["銘柄名"] = reindexed["name"].fillna(pd.Series(df.index.astype(str), index=df.index)).astype(str) if "name" in reindexed.columns else pd.Series(df.index.astype(str), index=df.index)
    else:
        df["業種"]   = "-"
        df["規模"]   = "-"
        df["銘柄名"] = pd.Series(df.index.astype(str), index=df.index)

    df["銘柄名"] = df["銘柄名"].apply(lambda x: x[:9] + "…" if len(str(x)) > 9 else x)
    df["業種"]   = df["業種"].apply(lambda x: x[:7]  + "…" if len(str(x)) > 7  else x)
    df["スコア"] = df.apply(calc_score, axis=1)

    df = df.reset_index()
    df.insert(0, "順位", range(1, len(df) + 1))

    # ⑥-1 列順: 順位→銘柄名→コード→スコア→規模→売買代金…
    col_order = [
        "順位","銘柄名","code","スコア",
        "規模","売買代金(億円)","売買代金前日比(補正%)","5日平均比(補正%)",
        "出来高(千株)","出来高前日比(補正%)",
        "当日騰落率(%)","20日騰落率(%)","60日騰落率(%)",
        "業種",
    ]
    return df[[c for c in col_order if c in df.columns]], progress_rate


# ── 列定義（③スクリーニングと同じ幅） ────────────
_RK_COLS = [
    ("銘柄名",              "銘 柄 名",          0.105),
    ("code",               "コード",            0.046),
    ("スコア",              "スコア",            0.042),
    ("規模",               "規模",              0.036),
    ("売買代金(億円)",       "売買代金\n(億円)",  0.068),
    ("売買代金前日比(補正%)", "売買代金\n前日比*", 0.068),
    ("5日平均比(補正%)",     "5日平均\n比*",     0.065),
    ("出来高(千株)",         "出来高\n(千株)",    0.062),
    ("出来高前日比(補正%)",  "出来高\n前日比*",   0.065),
    ("当日騰落率(%)",        "当日\nとう落",        0.065),
    ("20日騰落率(%)",        "20日\nとう落",        0.065),
    ("60日騰落率(%)",        "60日\nとう落",        0.065),
    ("業種",               "業　種",             0.083),
]

_SC_COLS = [
    ("銘柄名",              "銘 柄 名",          0.115),
    ("code",               "コード",            0.050),
    ("スコア",              "スコア",            0.048),
    ("規模",               "規模",              0.038),
    ("売買代金(億円)",       "売買代金\n(億円)",  0.073),
    ("売買代金前日比(補正%)", "売買代金\n前日比*", 0.073),
    ("5日平均比(補正%)",     "5日平均\n比*",     0.070),
    ("出来高(千株)",         "出来高\n(千株)",    0.067),
    ("出来高前日比(補正%)",  "出来高\n前日比*",   0.070),
    ("当日騰落率(%)",        "当日\nとう落",        0.070),
    ("20日騰落率(%)",        "20日\nとう落",        0.070),
    ("60日騰落率(%)",        "60日\nとう落",        0.070),
    ("業種",               "業　種",             0.086),
]

def _pct_color(val) -> str:
    try:
        v = float(val)
        if v > 0: return RK_POS
        if v < 0: return RK_NEG
    except:
        pass
    return RK_TEXT

def _score_color(val) -> str:
    try:
        v = int(val)
        if v >= 40:  return "#ff4444"
        if v >= 20:  return RK_SCORE_H
        if v >= 5:   return "#ffaa44"
        if v <= -40: return "#00ccff"
        if v <= -20: return RK_SCORE_L
        if v <= -5:  return "#88ddcc"
    except:
        pass
    return RK_TEXT

def _scale_color(val) -> str:
    if val == "超大型": return "#ff9900"
    if val == "大型":   return "#ffd700"
    if val == "中型":   return "#aaaaff"
    if val == "小型":   return RK_SUB
    return RK_SUB

def _fmt(col: str, val) -> str:
    try:
        v = float(val)
        if pd.isna(v): return "-"
        if col == "スコア":  return f"{int(round(v)):+d}"
        if "%" in col:      return f"{int(round(v)):+d}%"
        if "億円" in col:   return str(int(round(v)))
        if "千株" in col:   return str(int(round(v)))
        return str(val)
    except Exception:
        s = str(val)
        return s if s and s != "nan" else "-"


def _draw_ranking_rows(ax, subset, col_defs, n_rows, is_long=None):
    """行を描画"""
    total_w = sum(w for _,_,w in col_defs)
    margin  = (1.0 - total_w) / 2
    xs = [margin]
    for _,_,w in col_defs:
        xs.append(xs[-1] + w)

    for ri, (_, row) in enumerate(subset.iterrows()):
        y  = n_rows - 1 - ri
        if is_long is True:
            bg = "#0d1a0d" if ri % 2 == 0 else "#0a150a"
        elif is_long is False:
            bg = "#1a0d0d" if ri % 2 == 0 else "#150a0a"
        else:
            bg = RK_PANEL if ri % 2 == 0 else RK_BG

        ax.add_patch(mpatches.FancyBboxPatch(
            (0, y+0.04), 1, 0.90,
            boxstyle="round,pad=0.001",
            linewidth=0.3, edgecolor=RK_BORDER if is_long is None else ("#1a3a1a" if is_long else "#3a1a1a"),
            facecolor=bg))

        orig_rank = int(row.get("順位", ri+1))
        if orig_rank == 1:    badge_c = RK_GOLD
        elif orig_rank == 2:  badge_c = RK_SILVER
        elif orig_rank == 3:  badge_c = RK_BRONZE
        elif orig_rank <= 10: badge_c = "#c0392b"
        else:                 badge_c = "#2c3e50"

        ax.add_patch(mpatches.FancyBboxPatch(
            (0.0005, y+0.10), 0.014, 0.76,
            boxstyle="round,pad=0.001", linewidth=0, facecolor=badge_c))
        ax.text(0.0075, y+0.49, str(orig_rank),
                ha="center", va="center", fontsize=10.5, fontweight="bold",
                color="white" if orig_rank > 3 else "#1a1a1a")

        for i, (col_key, _, _) in enumerate(col_defs):
            val = row.get(col_key, "")
            txt = _fmt(col_key, val)
            cx  = (xs[i]+xs[i+1])/2

            if col_key == "スコア":
                color = _score_color(val); fw = "bold"; fs = 12.5
            elif col_key == "規模":
                color = _scale_color(txt); fw = "bold"; fs = 10.0
            elif col_key == "当日騰落率(%)":
                color = _pct_color(val); fw = "bold"; fs = 13.5
            elif "%" in col_key:
                color = _pct_color(val); fw = "bold"; fs = 12.0
            elif col_key == "銘柄名":
                color = RK_TEXT; fw = "normal"; fs = 10.0
            elif col_key == "業種":
                color = RK_TEXT; fw = "normal"; fs = 10.0
            else:
                color = RK_TEXT; fw = "normal"; fs = 11.5

            ax.text(cx, y+0.49, txt,
                    ha="center", va="center",
                    fontsize=fs, color=color, fontweight=fw, clip_on=True)


def _draw_header(ax, col_defs, n_rows, hdr_color=None, label_color=None):
    hdr_color   = hdr_color   or RK_HEADER
    label_color = label_color or RK_ACCENT2
    total_w = sum(w for _,_,w in col_defs)
    margin  = (1.0 - total_w) / 2
    xs = [margin]
    for _,_,w in col_defs:
        xs.append(xs[-1] + w)
    hdr_y = n_rows + 0.05
    ax.add_patch(mpatches.FancyBboxPatch(
        (0, hdr_y-0.02), 1, 0.94,
        boxstyle="round,pad=0.002", linewidth=0, facecolor=hdr_color))
    for i, (_, label, _) in enumerate(col_defs):
        ax.text((xs[i]+xs[i+1])/2, hdr_y+0.39, label,
                ha="center", va="center",
                fontsize=10.0, fontweight="bold", color=label_color)
    return xs


def _prog_label(progress_rate):
    pct  = progress_rate * 100
    mult = 1 / progress_rate if progress_rate > 0 else 1.0
    if progress_rate >= 0.95:
        return f"進捗率: {pct:.1f}%（終日データ）", RK_ACCENT2
    return f"進捗率: {pct:.1f}%（補正 ×{mult:.1f}倍）  ＊前日比は補正済み", RK_GOLD


def build_ranking_image(df, date_str, rank_start, rank_end, progress_rate=1.0, show_score=True):
    """売買代金順ランキング画像（1-20, 21-40, 41-60）"""
    subset = df[(df["順位"] >= rank_start) & (df["順位"] <= rank_end)].copy()
    n_rows = len(subset)
    col_defs = _RK_COLS if show_score else [c for c in _RK_COLS if c[0] != "スコア"]

    fig_w, fig_h = 26, 2.0 + n_rows * 0.65
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=RK_BG)
    fig.patch.set_facecolor(RK_BG)

    # タイトルバー
    ta = fig.add_axes([0, 0.918, 1, 0.082])
    ta.set_facecolor("#16163a"); ta.axis("off")
    ta.text(0.010, 0.62, f"売買代金ランキング  ―  {date_str}",
            fontsize=20, fontweight="bold", color=RK_TEXT,
            va="center", ha="left", transform=ta.transAxes)
    pl, pc = _prog_label(progress_rate)
    ta.text(0.010, 0.15, pl, fontsize=9.5, color=pc, fontweight="bold",
            va="center", ha="left", transform=ta.transAxes)
    bc = {(1,20): RK_ACCENT, (21,40): "#9b59b6", (41,60): "#2980b9"}.get((rank_start,rank_end), RK_ACCENT)
    ta.text(0.990, 0.5, f"{rank_start}〜{rank_end}位",
            fontsize=18, fontweight="bold", color=bc,
            va="center", ha="right", transform=ta.transAxes)

    ax = fig.add_axes([0.001, 0.005, 0.998, 0.905])
    ax.set_facecolor(RK_BG)
    ax.set_xlim(0,1); ax.set_ylim(0, n_rows+1); ax.axis("off")
    _draw_header(ax, col_defs, n_rows)
    _draw_ranking_rows(ax, subset, col_defs, n_rows, is_long=None)

    fig.text(0.990, 0.001,
             "データ: J-Quants API  ／  ＊印は市場進捗率補正済み（上位30社ベース）",
             fontsize=7.5, color=RK_SUB, va="bottom", ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=RK_BG)
    plt.close(fig); buf.seek(0)
    return buf.read()


def build_screening_image(df, date_str, progress_rate=1.0, long_n=15, short_n=10, show_score=True):
    """④ スコアランキング: ロング上位→ショート下位を縦に並べる"""
    df_sorted  = df.sort_values("スコア", ascending=False).reset_index(drop=True)
    long_df    = df_sorted.head(long_n).copy()
    # ⑤ ショートはスコアが最も低い順（マイナス絶対値が高い順）
    short_df   = df_sorted.tail(short_n).sort_values("スコア", ascending=True).reset_index(drop=True)

    n_long  = len(long_df)
    n_short = len(short_df)
    n_total = n_long + n_short

    sc_cols = _SC_COLS if show_score else [c for c in _SC_COLS if c[0] != "スコア"]

    fig_w   = 26
    row_h   = 0.62
    sep     = 1.2   # ロング・ショート間のスペース（行単位）
    fig_h   = 3.0 + n_total * row_h + sep * row_h

    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=RK_BG)
    fig.patch.set_facecolor(RK_BG)

    # 大タイトル
    fig.text(0.5, 0.985, f"スクリーニング  ―  {date_str}",
             fontsize=20, fontweight="bold", color=RK_TEXT, ha="center", va="top")
    pl, pc = _prog_label(progress_rate)
    fig.text(0.5, 0.966, pl, fontsize=9.5, color=pc, fontweight="bold",
             ha="center", va="top")

    # 高さ計算（figの割合）
    total_h_units = n_total * row_h + sep * row_h + 1.5  # 1.5は余白
    def h_frac(rows):
        return rows * row_h / fig_h

    # ロングのaxの縦位置
    long_h   = h_frac(n_long)
    short_h  = h_frac(n_short)
    footer   = 0.04
    sep_frac = h_frac(sep)

    short_bottom = footer
    short_top    = short_bottom + short_h
    long_bottom  = short_top + sep_frac
    long_top     = long_bottom + long_h

    # ── ロングセクション ─────────────────────────
    # タイトル帯
    lt = fig.add_axes([0.01, long_top, 0.98, 0.045])
    lt.set_facecolor("#1a3a1a"); lt.axis("off")
    lt.text(0.5, 0.5, f"🟢  ロング候補  スコア上位 {n_long}銘柄",
            fontsize=14, fontweight="bold", color="#88ff88",
            ha="center", va="center", transform=lt.transAxes)

    la = fig.add_axes([0.01, long_bottom, 0.98, long_h])
    la.set_facecolor(RK_BG)
    la.set_xlim(0,1); la.set_ylim(0, n_long+1); la.axis("off")
    _draw_header(la, sc_cols, n_long, hdr_color="#1e3a1e", label_color="#88ff88")
    _draw_ranking_rows(la, long_df, sc_cols, n_long, is_long=True)

    # ── 区切り線 ─────────────────────────────────
    sep_mid = short_top + sep_frac * 0.5
    fig.add_axes([0.01, sep_mid - 0.002, 0.98, 0.004]).set_facecolor("#444466")
    fig.axes[-1].axis("off")

    # ── ショートセクション ───────────────────────
    st2 = fig.add_axes([0.01, short_top + sep_frac * 0.05, 0.98, 0.045])
    st2.set_facecolor("#3a1a1a"); st2.axis("off")
    st2.text(0.5, 0.5, f"🔴  ショート候補  スコア下位 {n_short}銘柄（スコアが低い順）",
             fontsize=14, fontweight="bold", color="#ff8888",
             ha="center", va="center", transform=st2.transAxes)

    sa = fig.add_axes([0.01, short_bottom, 0.98, short_h])
    sa.set_facecolor(RK_BG)
    sa.set_xlim(0,1); sa.set_ylim(0, n_short+1); sa.axis("off")
    _draw_header(sa, sc_cols, n_short, hdr_color="#3a1e1e", label_color="#ff8888")
    _draw_ranking_rows(sa, short_df, sc_cols, n_short, is_long=False)

    fig.text(0.99, 0.005,
             "データ: J-Quants API  ／  ＊印は市場進捗率補正済み（上位30社）",
             fontsize=7.5, color=RK_SUB, va="bottom", ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=RK_BG)
    plt.close(fig); buf.seek(0)
    return buf.read()
