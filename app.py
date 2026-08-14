import math
from datetime import date, timedelta
import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Nifty Quant Flow", page_icon="📊", layout="wide")

V2_BASE = "https://api.upstox.com/v2"
V3_BASE = "https://api.upstox.com/v3"
INSTRUMENT_SEARCH_URL = f"{V2_BASE}/instruments/search"

# Reference weights from the July 31, 2026 NSE factsheets.
# These are top constituents only; upload the complete current weight file
# for exact full-index analysis.
NIFTY_REFERENCE = {
    "HDFCBANK": 10.27, "ICICIBANK": 9.22, "RELIANCE": 7.92,
    "BHARTIARTL": 5.37, "LT": 4.13, "SBIN": 3.81,
    "INFY": 3.55, "AXISBANK": 3.16, "BAJFINANCE": 2.74, "M&M": 2.72,
}
BANK_REFERENCE = {
    "HDFCBANK": 18.20, "ICICIBANK": 14.86, "SBIN": 10.09,
    "KOTAKBANK": 9.32, "AXISBANK": 8.81, "FEDERALBNK": 7.29,
    "INDUSINDBK": 5.50, "AUBANK": 4.71, "IDFCFIRSTB": 4.67,
    "BANKBARODA": 3.58,
}

def get_secret_token():
    try:
        return str(st.secrets.get("UPSTOX_ACCESS_TOKEN", "")).strip()
    except Exception:
        return ""

def api_headers(token):
    return {"Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"}

def api_get(url, token, params=None, timeout=25):
    try:
        r = requests.get(url, headers=api_headers(token), params=params, timeout=timeout)
    except requests.RequestException as e:
        raise RuntimeError(f"Network error contacting Upstox: {e}") from e
    if not r.ok:
        try:
            body = r.json()
        except Exception:
            body = r.text[:500]
        raise RuntimeError(f"Upstox HTTP {r.status_code}: {body}")
    return r.json()

@st.cache_data(ttl=21600, show_spinner=False)
def resolve_equity(token, symbol):
    data = api_get(INSTRUMENT_SEARCH_URL, token, {
        "query": symbol, "exchanges": "NSE", "segments": "EQ",
        "instrument_types": "EQ", "page_number": 1, "records": 30
    })
    rows = data.get("data", []) or []
    exact = [x for x in rows if x.get("exchange") == "NSE"
             and x.get("segment") == "NSE_EQ"
             and x.get("instrument_type") == "EQ"
             and str(x.get("trading_symbol", "")).upper() == symbol.upper()]
    if exact:
        return exact[0]
    candidates = [x for x in rows if x.get("exchange") == "NSE"
                  and x.get("segment") == "NSE_EQ"
                  and x.get("instrument_type") == "EQ"]
    return candidates[0] if candidates else None

@st.cache_data(ttl=15, show_spinner=False)
def get_ohlc(token, keys):
    result = {}
    for i in range(0, len(keys), 100):
        batch = keys[i:i+100]
        data = api_get(f"{V3_BASE}/market-quote/ohlc", token, {
            "instrument_key": ",".join(batch), "interval": "1d"
        })
        result.update(data.get("data", {}) or {})
    return result

@st.cache_data(ttl=900, show_spinner=False)
def get_daily_history(token, instrument_key, days_back=90):
    end = date.today()
    start = end - timedelta(days=days_back)
    url = f"{V3_BASE}/historical-candle/{instrument_key}/days/1/{end.isoformat()}/{start.isoformat()}"
    data = api_get(url, token)
    candles = (data.get("data", {}) or {}).get("candles", []) or []
    if not candles:
        return pd.DataFrame(columns=["timestamp","open","high","low","close","volume","oi"])
    df = pd.DataFrame(candles, columns=["timestamp","open","high","low","close","volume","oi"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for c in ["open","high","low","close","volume","oi"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("timestamp").reset_index(drop=True)

def load_weights(uploaded, index_name):
    if uploaded is not None:
        raw = pd.read_csv(uploaded)
        lookup = {c.lower().strip(): c for c in raw.columns}
        if "symbol" not in lookup or "weight_pct" not in lookup:
            raise ValueError("Weight CSV must contain columns: symbol, weight_pct")
        df = raw.rename(columns={lookup["symbol"]: "symbol", lookup["weight_pct"]: "weight_pct"})
        df = df[["symbol", "weight_pct"]].copy()
        df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
        df["weight_pct"] = pd.to_numeric(df["weight_pct"], errors="coerce")
        df = df.dropna().query("weight_pct > 0")
        return df.sort_values("weight_pct", ascending=False).reset_index(drop=True), True
    ref = NIFTY_REFERENCE if index_name == "NIFTY 50" else BANK_REFERENCE
    return pd.DataFrame({"symbol": list(ref), "weight_pct": list(ref.values())}), False

def calculate(df, lookback):
    df = df.copy()
    df["return_pct"] = pd.to_numeric(df["return_pct"], errors="coerce")
    df["weight_pct"] = pd.to_numeric(df["weight_pct"], errors="coerce")
    df = df.dropna(subset=["return_pct", "weight_pct"])
    df["contribution_pct"] = df["weight_pct"] * df["return_pct"] / 100.0
    net = df["contribution_pct"].sum()
    positive = df.loc[df.contribution_pct > 0, "contribution_pct"].sum()
    negative = df.loc[df.contribution_pct < 0, "contribution_pct"].sum()
    breadth = (df["return_pct"] > 0).mean() * 100 if len(df) else np.nan
    weighted_var = 0.0
    for _, r in df.iterrows():
        hist = r.get("history")
        if hist is None or len(hist) < 8:
            continue
        ret = hist.pct_change().dropna().tail(lookback)
        if len(ret) >= 5:
            weighted_var += ((float(r.weight_pct)/100.0) * float(ret.std())) ** 2
    daily_vol = math.sqrt(weighted_var) if weighted_var > 0 else np.nan
    return df, net, positive, negative, breadth, daily_vol

def bias(net, breadth):
    if net >= 0.30 and breadth >= 55: return "STRONG BULLISH"
    if net >= 0.10: return "BULLISH"
    if net <= -0.30 and breadth <= 45: return "STRONG BEARISH"
    if net <= -0.10: return "BEARISH"
    return "NEUTRAL / MIXED"

def confidence(net, breadth, coverage):
    d = min(abs(net)/0.75, 1)
    b = min(abs(breadth-50)/35, 1)
    c = min(coverage/80, 1)
    return round(100*(0.45*d + 0.35*b + 0.20*c))

st.title("📊 Nifty Quant Flow Engine")
st.caption("Upstox V3 market data • weighted constituent pressure • volatility range")

secret = get_secret_token()
with st.sidebar:
    st.header("Controls")
    token = secret or st.text_input("Upstox access token", type="password")
    if secret:
        st.success("Token loaded from Streamlit Secrets")
    else:
        st.warning("For production, use UPSTOX_ACCESS_TOKEN in Streamlit Secrets.")
    index_name = st.selectbox("Index", ["NIFTY 50", "NIFTY BANK"])
    uploaded = st.file_uploader("Current full index weights CSV (recommended)", type=["csv"])
    lookback = st.slider("Volatility lookback", 10, 60, 20)
    horizon = st.selectbox("Expected move horizon", [1,3,5],
                           format_func=lambda x: f"{x} trading day" + ("" if x==1 else "s"))
    run = st.button("🚀 Run analysis", type="primary", use_container_width=True)

if not run:
    st.info("Configure the Upstox token, choose an index, then click Run analysis.")
    st.stop()

if not token:
    st.error("No Upstox token found. Add UPSTOX_ACCESS_TOKEN to Streamlit Secrets.")
    st.stop()

try:
    weights, full_weights = load_weights(uploaded, index_name)
    if not full_weights:
        st.warning("Using only the built-in top-constituent reference weights. Upload the latest full weight CSV for exact index pressure.")

    progress = st.progress(0, text="Resolving Upstox instruments...")
    resolved = []
    for n, (_, r) in enumerate(weights.iterrows(), 1):
        try:
            inst = resolve_equity(token, r.symbol)
        except Exception:
            inst = None
        resolved.append({
            "symbol": r.symbol, "weight_pct": float(r.weight_pct),
            "instrument_key": inst.get("instrument_key") if inst else None,
            "name": (inst.get("short_name") or inst.get("name")) if inst else None
        })
        progress.progress(n/len(weights), text=f"Resolving {r.symbol}...")
    progress.empty()

    resolved_df = pd.DataFrame(resolved).dropna(subset=["instrument_key"])
    if resolved_df.empty:
        st.error("No NSE equity instruments resolved. Check the token and market-data permissions.")
        st.stop()

    progress = st.progress(0, text="Getting current quotes...")
    quotes = get_ohlc(token, resolved_df.instrument_key.tolist())
    progress.empty()

    rows = []
    progress = st.progress(0, text="Calculating pressure...")
    for n, (_, r) in enumerate(resolved_df.iterrows(), 1):
        key = r.instrument_key
        q = quotes.get(key) or quotes.get(key.replace("|", ":")) or {}
        live, prev = q.get("live_ohlc") or {}, q.get("prev_ohlc") or {}
        last = q.get("last_price") or live.get("close")
        prev_close = prev.get("close")
        hist = pd.DataFrame()
        if last is None or prev_close in (None, 0):
            try:
                hist = get_daily_history(token, key, max(lookback+10, 45))
                if len(hist) >= 2:
                    last = float(hist.iloc[-1].close) if last is None else last
                    prev_close = float(hist.iloc[-2].close)
            except Exception:
                pass
        if last is not None and prev_close not in (None, 0):
            try:
                if hist.empty:
                    hist = get_daily_history(token, key, max(lookback+10, 45))
            except Exception:
                pass
            rows.append({
                "symbol": r.symbol, "name": r.name, "weight_pct": r.weight_pct,
                "instrument_key": key, "price": float(last),
                "prev_close": float(prev_close),
                "return_pct": (float(last)/float(prev_close)-1)*100,
                "volume": live.get("volume", np.nan),
                "history": hist["close"] if not hist.empty else None
            })
        progress.progress(n/len(resolved_df), text=f"Analyzing {r.symbol}...")
    progress.empty()

    if not rows:
        st.error("No usable market data returned. Check token validity and Upstox market-data access.")
        st.stop()

    df, net, positive, negative, breadth, daily_vol = calculate(pd.DataFrame(rows), lookback)
    coverage = float(df.weight_pct.sum())
    move = daily_vol * math.sqrt(horizon) * 100 if np.isfinite(daily_vol) else np.nan
    directional = net * math.sqrt(horizon)
    model_bias = bias(net, breadth)
    conf = confidence(net, breadth, coverage)

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Model bias", model_bias)
    c2.metric("Net pressure", f"{net:+.3f}%")
    c3.metric("Breadth", f"{breadth:.1f}%")
    c4.metric("Weight coverage", f"{coverage:.1f}%")
    c5.metric("Confidence", f"{conf}/100")

    st.subheader("Expected move")
    if np.isfinite(move):
        st.write(f"**Volatility range:** ±{move:.2f}% over the next {horizon} trading day{'s' if horizon != 1 else ''}.")
        st.caption(f"Directional pressure component: {directional:+.2f}%. This is a heuristic indicator, not a guaranteed target.")
    else:
        st.write("Not enough history to estimate volatility.")

    df = df.sort_values("contribution_pct", ascending=False)
    left,right = st.columns(2)
    with left:
        st.markdown("### 🟢 Positive pulls")
        x = df[df.contribution_pct > 0].head(10)
        st.dataframe(x[["symbol","weight_pct","return_pct","contribution_pct","price"]].rename(
            columns={"symbol":"Stock","weight_pct":"Weight %","return_pct":"Move %",
                     "contribution_pct":"Index Pull %","price":"Price"}).round(3),
                     use_container_width=True, hide_index=True)
    with right:
        st.markdown("### 🔴 Negative pulls")
        x = df[df.contribution_pct < 0].sort_values("contribution_pct").head(10)
        st.dataframe(x[["symbol","weight_pct","return_pct","contribution_pct","price"]].rename(
            columns={"symbol":"Stock","weight_pct":"Weight %","return_pct":"Move %",
                     "contribution_pct":"Index Pull %","price":"Price"}).round(3),
                     use_container_width=True, hide_index=True)

    st.subheader("Full ranking")
    table = df.drop(columns=["history"], errors="ignore").copy()
    table["direction"] = np.where(table.contribution_pct > 0, "UP", "DOWN")
    st.dataframe(table[["symbol","name","weight_pct","price","prev_close","return_pct","contribution_pct","direction"]].rename(
        columns={"symbol":"Stock","name":"Name","weight_pct":"Weight %","price":"Price",
                 "prev_close":"Prev Close","return_pct":"Move %",
                 "contribution_pct":"Index Pull %","direction":"Direction"}).round(3),
                 use_container_width=True, hide_index=True)

    st.download_button("⬇️ Download analysis CSV", table.to_csv(index=False).encode(),
                       file_name=f"{index_name.lower().replace(' ','_')}_flow.csv",
                       mime="text/csv")

    with st.expander("Model math"):
        st.markdown("""
For each constituent:

`Index Pull % = Index Weight % × Stock Return % / 100`

Net pressure is the sum of all constituent pulls.

Breadth is the percentage of constituents rising.

Expected move uses weighted recent daily volatility and square-root-of-time scaling.

This is an analytical research model, not a guaranteed prediction or investment recommendation.
""")

except Exception as e:
    st.error("The analysis failed.")
    st.exception(e)
