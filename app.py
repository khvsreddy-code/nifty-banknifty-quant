
import io
import json
import math
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Nifty Weighted Flow Engine", layout="wide")

UPSTOX_BASE = "https://api.upstox.com/v3"
INSTRUMENT_SEARCH = "https://api.upstox.com/v3/instruments/search"

# Starter universe. The weights are intentionally kept in a separate CSV so they
# can be replaced with the latest NSE constituent/weightage file.
NIFTY50_STARTER = {
    "HDFCBANK": 10.73, "RELIANCE": 8.78, "ICICIBANK": 8.21, "BHARTIARTL": 5.26,
    "LT": 4.28, "SBIN": 4.03, "INFY": 3.76, "AXISBANK": 3.31,
    "ITC": 2.76, "KOTAKBANK": 2.56
}
BANKNIFTY_STARTER = {
    "HDFCBANK": 18.37, "ICICIBANK": 13.55, "AXISBANK": 10.02,
    "SBIN": 9.93, "KOTAKBANK": 9.67, "FEDERALBNK": 6.27,
    "INDUSINDBK": 5.35, "AUBANK": 4.97, "BANKBARODA": 4.34,
    "IDFCFIRSTB": 4.12
}

def headers(token):
    return {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}

def api_get(url, token, params=None, timeout=20):
    r = requests.get(url, headers=headers(token), params=params, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"Upstox HTTP {r.status_code}: {r.text[:500]}")
    return r.json()

@st.cache_data(ttl=3600)
def search_instrument(token, symbol):
    data = api_get(
        INSTRUMENT_SEARCH, token,
        {"query": symbol, "segment": "EQ", "exchange": "NSE", "page_number": 1, "records": 20}
    )
    rows = data.get("data", [])
    rows = [x for x in rows if x.get("segment") == "NSE_EQ" and x.get("instrument_type") in ("EQ", "BE")]
    exact = [x for x in rows if x.get("trading_symbol", "").upper() == symbol.upper()]
    return (exact or rows)[0] if (exact or rows) else None

def historical(token, instrument_key, start, end, interval="days", n="1"):
    url = f"{UPSTOX_BASE}/historical-candle/{instrument_key}/{interval}/{n}/{end}/{start}"
    payload = api_get(url, token)
    candles = payload.get("data", {}).get("candles", [])
    if not candles:
        return pd.DataFrame(columns=["timestamp","open","high","low","close","volume","oi"])
    df = pd.DataFrame(candles, columns=["timestamp","open","high","low","close","volume","oi"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for c in ["open","high","low","close","volume","oi"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)

def ohlc_quotes(token, keys):
    # V3 OHLC endpoint accepts one or more instruments.
    out = {}
    for i in range(0, len(keys), 50):
        chunk = keys[i:i+50]
        payload = api_get(
            f"{UPSTOX_BASE}/market-quote/ohlc",
            token,
            {"instrument_key": ",".join(chunk), "interval": "1d"}
        )
        out.update(payload.get("data", {}))
    return out

def extract_quote(q):
    # Upstox quote object names can vary by response shape; use live_ohlc first.
    live = q.get("live_ohlc") or {}
    prev = q.get("prev_ohlc") or {}
    close = live.get("close")
    if close is None:
        close = q.get("last_price") or q.get("ltp")
    prev_close = prev.get("close") or q.get("cp")
    return float(close) if close is not None else np.nan, float(prev_close) if prev_close is not None else np.nan

def weighted_model(df, lookback=20, annualization=252):
    x = df.copy()
    x["contribution_pct"] = x["weight_pct"] * x["return_pct"] / 100.0
    x["weighted_return_pct"] = x["contribution_pct"]
    x["direction_score"] = x["weight_pct"] * x["return_pct"]
    x = x.sort_values("contribution_pct", ascending=False)

    net = x["contribution_pct"].sum()
    pos = x.loc[x.contribution_pct > 0, "contribution_pct"].sum()
    neg = x.loc[x.contribution_pct < 0, "contribution_pct"].sum()
    breadth = (x["return_pct"] > 0).mean() * 100

    # Weighted historical daily volatility, used only as a range estimator.
    vols = []
    for _, r in x.iterrows():
        if isinstance(r.get("hist"), pd.Series) and len(r["hist"]) > 5:
            ret = r["hist"].pct_change().dropna().tail(lookback)
            vols.append((r["weight_pct"] / 100.0, ret.std()))
    weighted_daily_vol = np.sqrt(sum((w * v) ** 2 for w, v in vols)) if vols else np.nan

    expected_1d = weighted_daily_vol * 100 if np.isfinite(weighted_daily_vol) else np.nan
    return x, net, pos, neg, breadth, expected_1d

def load_weights(upload, index_name):
    if upload is not None:
        raw = pd.read_csv(upload)
        required = {"symbol","weight_pct"}
        if not required.issubset(raw.columns):
            raise ValueError("CSV must contain: symbol, weight_pct")
        raw = raw[["symbol","weight_pct"]].copy()
        raw["symbol"] = raw["symbol"].astype(str).str.upper().str.strip()
        raw["weight_pct"] = pd.to_numeric(raw["weight_pct"], errors="coerce")
        return raw.dropna()

    d = NIFTY50_STARTER if index_name == "NIFTY 50" else BANKNIFTY_STARTER
    return pd.DataFrame({"symbol": list(d), "weight_pct": list(d.values())})

st.title("Nifty / Bank Nifty Weighted Flow Engine")
st.caption("Upstox V3 market data + NSE index weights + transparent contribution math")

with st.sidebar:
    st.header("Connection")
    token = st.text_input("Upstox access token", type="password")
    index_name = st.selectbox("Index", ["NIFTY 50", "NIFTY BANK"])
    uploaded = st.file_uploader("Latest NSE weightage CSV (optional)", type=["csv"])
    lookback = st.slider("Volatility lookback (days)", 5, 60, 20)
    horizon = st.selectbox("Expected move horizon", ["1 trading day", "5 trading days"])
    run = st.button("Run analysis", type="primary")

st.info(
    "For production use, upload the latest NSE weightage file. "
    "The included starter weights are only a small seed set to demonstrate the app."
)

if run:
    if not token:
        st.error("Enter your Upstox access token.")
        st.stop()

    try:
        weights = load_weights(uploaded, index_name)
        weights = weights.sort_values("weight_pct", ascending=False).reset_index(drop=True)

        progress = st.progress(0)
        rows = []
        end = date.today()
        start = end - timedelta(days=max(90, lookback * 3))

        for i, r in weights.iterrows():
            symbol = r["symbol"]
            inst = search_instrument(token, symbol)
            if not inst:
                rows.append({"symbol": symbol, "weight_pct": r["weight_pct"], "error": "Instrument not found"})
                progress.progress((i + 1) / len(weights))
                continue

            hist = historical(token, inst["instrument_key"], start.isoformat(), end.isoformat())
            if hist.empty:
                rows.append({"symbol": symbol, "weight_pct": r["weight_pct"], "error": "No history"})
                progress.progress((i + 1) / len(weights))
                continue

            last = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else last
            ret = (last["close"] / prev["close"] - 1) * 100 if prev["close"] else np.nan

            rows.append({
                "symbol": symbol,
                "name": inst.get("short_name") or inst.get("name"),
                "instrument_key": inst["instrument_key"],
                "weight_pct": float(r["weight_pct"]),
                "price": float(last["close"]),
                "return_pct": float(ret),
                "volume": float(last["volume"]),
                "hist": hist["close"]
            })
            progress.progress((i + 1) / len(weights))

        df = pd.DataFrame(rows)
        valid = df[df.get("return_pct").notna()].copy()
        if valid.empty:
            st.error("No valid market data returned.")
            st.stop()

        modeled, net, pos, neg, breadth, expected_1d = weighted_model(valid, lookback)
        scale = math.sqrt(5) if horizon.startswith("5") else 1.0
        expected_move = expected_1d * scale if np.isfinite(expected_1d) else np.nan

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Weighted direction", f"{net:+.2f}%")
        c2.metric("Positive pull", f"{pos:+.2f}%")
        c3.metric("Negative pull", f"{neg:+.2f}%")
        c4.metric("Breadth", f"{breadth:.1f}%")

        if net > 0.15:
            bias = "BULLISH"
        elif net < -0.15:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL / MIXED"

        st.subheader(f"{index_name}: model output")
        st.write(f"**Model bias:** {bias}")
        if np.isfinite(expected_move):
            st.write(f"**Estimated {horizon.lower()} move:** ±{expected_move:.2f}%")
            st.caption(
                "This is a volatility-based range, not a guaranteed target. "
                "The directional score is a weighted snapshot of constituent returns."
            )

        st.subheader("What is pulling the index?")
        display = modeled.drop(columns=["hist"], errors="ignore").copy()
        display["contribution_pct"] = display["contribution_pct"].round(3)
        display["weight_pct"] = display["weight_pct"].round(2)
        display["return_pct"] = display["return_pct"].round(2)
        st.dataframe(
            display[["symbol","name","weight_pct","return_pct","contribution_pct","price","volume","error"]]
            if "error" in display.columns else
            display[["symbol","name","weight_pct","return_pct","contribution_pct","price","volume"]],
            use_container_width=True,
            hide_index=True
        )

        st.subheader("Interpretation")
        top_up = modeled.head(5)
        top_down = modeled.tail(5).sort_values("contribution_pct")
        st.write("**Largest positive pulls:** " + ", ".join(
            f"{r.symbol} ({r.contribution_pct:+.2f}%)" for _, r in top_up.iterrows() if r.contribution_pct > 0
        ))
        st.write("**Largest negative pulls:** " + ", ".join(
            f"{r.symbol} ({r.contribution_pct:+.2f}%)" for _, r in top_down.iterrows() if r.contribution_pct < 0
        ))

        st.download_button(
            "Download analysis CSV",
            modeled.drop(columns=["hist"], errors="ignore").to_csv(index=False).encode(),
            file_name=f"{index_name.lower().replace(' ','_')}_analysis.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.exception(e)

st.divider()
st.markdown(
    "**Math:** constituent contribution ≈ index weight × constituent return. "
    "Net contribution = sum of all constituent contributions. "
    "Expected move uses weighted historical volatility and √time scaling. "
    "It is a research indicator, not a trading signal or guaranteed prediction."
)
