import math
import threading
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from urllib.parse import quote
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Nifty / Bank Nifty OI Pulse Pro", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.stApp{background:#f4f7fb}.block-container{max-width:1500px;padding-top:1.1rem;padding-bottom:3rem}
h1,h2,h3{letter-spacing:-.025em;color:#172033}
[data-testid="stMetric"]{background:#fff;border:1px solid #e5e9f0;border-radius:14px;padding:.7rem 1rem;box-shadow:0 3px 14px rgba(15,23,42,.045)}
.level-stack{border:1px solid #e3e8ef;border-radius:16px;overflow:hidden;background:#fff;box-shadow:0 4px 18px rgba(15,23,42,.05)}
.lvl{display:grid;grid-template-columns:1fr 1fr 1.3fr;align-items:center;padding:9px 14px;border-bottom:1px solid #edf0f4}.lvl:last-child{border-bottom:0}
.lvl span{font-weight:700}.lvl b{text-align:center;font-size:16px}.lvl small{text-align:right;color:#64748b}
.redlvl{background:linear-gradient(90deg,#fff7f7,#fff)}.redlvl span,.redlvl b{color:#b42318}
.greenlvl{background:linear-gradient(90deg,#f5fff9,#fff)}.greenlvl span,.greenlvl b{color:#087443}
.spotlvl{background:#f8fafc}.spotlvl b{color:#172033;font-size:18px}.ext{opacity:.78}
.pulse-card{border:1px solid #e3e8ef;border-radius:13px;background:#fff;padding:11px 13px;margin:3px 0 9px;box-shadow:0 2px 9px rgba(15,23,42,.04)}
.pulse-top{font-size:12px;color:#64748b}.pulse-main{font-size:14px;font-weight:800;margin-top:5px}.pulse-sub{font-size:11px;color:#64748b;margin-top:4px}
div[data-testid="stExpander"]{border-color:#e1e6ee;border-radius:14px}
</style>
""",unsafe_allow_html=True)

IST = ZoneInfo("Asia/Kolkata")
API = "https://api.upstox.com/v2"
API3 = "https://api.upstox.com/v3"
VIX_KEY = "NSE_INDEX|India VIX"

INDEXES = {
    "NIFTY 50": {"key": "NSE_INDEX|Nifty 50", "step": 50, "strike_window": 14},
    "BANK NIFTY": {"key": "NSE_INDEX|Nifty Bank", "step": 100, "strike_window": 14},
}


# Feature governance: every live feature is tagged so the research lab can test whether
# it improves out-of-sample prediction, false-break rate, target hit rate, drawdown or R/R.
FEATURE_REGISTRY = {
    "futures_basis": {"label": "Futures basis / OI", "family": "derivatives"},
    "confluence": {"label": "Level confluence", "family": "levels"},
    "absorption": {"label": "Absorption / failed breakout", "family": "price_action"},
    "regime": {"label": "Market regime", "family": "regime"},
    "volume_profile": {"label": "Volume profile", "family": "price_structure"},
    "atm_pressure": {"label": "ATM pressure", "family": "options"},
    "iv_skew": {"label": "IV skew", "family": "volatility"},
    "breadth": {"label": "Constituent breadth", "family": "index_flow"},
    "vwap": {"label": "VWAP", "family": "price_structure"},
    "opening_range": {"label": "Opening range", "family": "price_structure"},
}

DEFAULT_FEATURE_WEIGHTS = {
    "futures_basis": 0.16, "confluence": 0.18, "absorption": 0.14, "regime": 0.12,
    "volume_profile": 0.08, "atm_pressure": 0.10, "iv_skew": 0.06,
    "breadth": 0.06, "vwap": 0.06, "opening_range": 0.04,
}

# Reference weights: official NSE Indices factsheet snapshot dated 30-Apr-2026.
# They are intentionally labeled reference weights because free-float weights change.
NIFTY_WEIGHTS = {
    "HDFCBANK": 10.73, "RELIANCE": 8.78, "ICICIBANK": 8.21, "BHARTIARTL": 5.26,
    "LT": 4.28, "SBIN": 4.03, "INFY": 3.76, "AXISBANK": 3.31, "ITC": 2.76,
    "KOTAKBANK": 2.56, "M&M": 2.50, "TCS": 2.35, "BAJFINANCE": 2.30,
    "HINDUNILVR": 1.81, "MARUTI": 1.70, "SUNPHARMA": 1.60, "NTPC": 1.58,
    "TITAN": 1.56, "ETERNAL": 1.54, "TATASTEEL": 1.53, "BEL": 1.39,
    "SHRIRAMFIN": 1.32, "ULTRACEMCO": 1.31, "HCLTECH": 1.28, "POWERGRID": 1.18,
    "HINDALCO": 1.17, "JSWSTEEL": 1.04,
}
BANK_WEIGHTS = {
    "HDFCBANK": 18.37, "ICICIBANK": 13.55, "AXISBANK": 10.02, "SBIN": 9.93,
    "KOTAKBANK": 9.67, "FEDERALBNK": 6.27, "INDUSINDBK": 5.35,
    "AUBANK": 4.97, "BANKBARODA": 4.34, "IDFCFIRSTB": 4.12,
    "PNB": 2.50, "CANBK": 2.40, "UNIONBANK": 2.20, "YESBANK": 1.80,
}

NIFTY_SYMBOLS = list(NIFTY_WEIGHTS)
BANK_SYMBOLS = list(BANK_WEIGHTS)

# The symbols below are resolved through the Upstox quote endpoint; users can upload
# a current weight CSV in the sidebar if they want exact current index weights.

COLS = [
    "strike", "ce_key", "pe_key", "ce_ltp", "ce_oi", "ce_prev_oi", "ce_vol", "ce_close", "ce_iv", "ce_delta", "ce_gamma", "ce_vega", "ce_theta", "ce_bid", "ce_ask", "ce_bid_qty", "ce_ask_qty",
    "pe_ltp", "pe_oi", "pe_prev_oi", "pe_vol", "pe_close", "pe_iv", "pe_delta", "pe_gamma", "pe_vega", "pe_theta", "pe_bid", "pe_ask", "pe_bid_qty", "pe_ask_qty",
    "ce_doi_day", "pe_doi_day", "ce_prem_pct", "pe_prem_pct",
]


def token_from_secrets():
    try:
        return str(st.secrets.get("UPSTOX_ACCESS_TOKEN", "")).strip()
    except Exception:
        return ""


def headers(token):
    return {"Accept": "application/json", "Authorization": f"Bearer {token}"}


def api_get(path, token, params=None, timeout=15):
    r = requests.get(f"{API}{path}", headers=headers(token), params=params, timeout=timeout)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    if not r.ok:
        raise RuntimeError(f"Upstox HTTP {r.status_code}: {body}")
    return body


def api_get3(path, token, params=None, timeout=15):
    r = requests.get(f"{API3}{path}", headers=headers(token), params=params, timeout=timeout)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    if not r.ok:
        raise RuntimeError(f"Upstox V3 HTTP {r.status_code}: {body}")
    return body


@st.cache_data(ttl=8, show_spinner=False)
def intraday_index_stats(token, key):
    d = api_get3(f"/historical-candle/intraday/{quote(key, safe='')}/minutes/1", token)
    candles = ((d.get("data") or {}).get("candles") or []) if isinstance(d, dict) else []
    if not candles:
        return {}
    rows = []
    for c in candles:
        if len(c) < 5: continue
        rows.append({"ts":c[0],"open":num(c[1]),"high":num(c[2]),"low":num(c[3]),"close":num(c[4]),"vol":num(c[5]) if len(c)>5 else 0})
    x = pd.DataFrame(rows).sort_values("ts")
    if x.empty: return {}
    last=float(x.close.iloc[-1]); op=float(x.open.iloc[0])
    ret5=(last/float(x.close.iloc[-6])-1)*100 if len(x)>=6 and x.close.iloc[-6] else 0
    ret15=(last/float(x.close.iloc[-16])-1)*100 if len(x)>=16 and x.close.iloc[-16] else 0
    first15=x.iloc[:15] if len(x)>=15 else x
    return {"open":op,"last":last,"ret5":ret5,"ret15":ret15,"high":float(x.high.max()),"low":float(x.low.min()),"or_high":float(first15.high.max()),"or_low":float(first15.low.min()),"bars":len(x)}


@st.cache_data(ttl=4, show_spinner=False)
def ltp_quotes(token, keys_csv):
    d = api_get("/market-quote/ltp", token, {"instrument_key": keys_csv})
    return d.get("data", {}) if isinstance(d, dict) else {}


def quote_from_data(data, key):
    q = data.get(key) or data.get(key.replace("|", ":"))
    if q is None and data:
        q = next(iter(data.values()))
    return q or {}


@st.cache_data(ttl=4, show_spinner=False)
def underlying_ltp(token, key):
    data = ltp_quotes(token, key)
    q = quote_from_data(data, key)
    return float(q.get("last_price") or 0), float(q.get("cp") or 0)


@st.cache_data(ttl=90, show_spinner=False)
def option_contracts(token, underlying_key):
    d = api_get("/option/contract", token, {"instrument_key": underlying_key})
    rows = d.get("data", []) or []
    return rows if isinstance(rows, list) else []


@st.cache_data(ttl=4, show_spinner=False)
def option_chain(token, underlying_key, expiry):
    d = api_get("/option/chain", token, {"instrument_key": underlying_key, "expiry_date": expiry})
    rows = d.get("data", []) if isinstance(d, dict) else []
    return rows if isinstance(rows, list) else []


def nearest_expiry(contracts):
    today = datetime.now(IST).date()
    exps = []
    for x in contracts:
        e = x.get("expiry") if isinstance(x, dict) else None
        if not e:
            continue
        try:
            d = date.fromisoformat(str(e)[:10])
            if d >= today:
                exps.append(d)
        except Exception:
            pass
    return min(exps).isoformat() if exps else None


def num(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def build_option_df(chain):
    rows = []
    for x in chain or []:
        if not isinstance(x, dict):
            continue
        strike = num(x.get("strike_price"), np.nan)
        if not np.isfinite(strike):
            continue
        c = x.get("call_options") or {}
        p = x.get("put_options") or {}
        cm = c.get("market_data") or {}
        pm = p.get("market_data") or {}
        cg = c.get("option_greeks") or {}
        pg = p.get("option_greeks") or {}
        ce_ltp, pe_ltp = num(cm.get("ltp")), num(pm.get("ltp"))
        ce_close, pe_close = num(cm.get("close_price")), num(pm.get("close_price"))
        ce_oi, pe_oi = num(cm.get("oi")), num(pm.get("oi"))
        ce_prev, pe_prev = num(cm.get("prev_oi")), num(pm.get("prev_oi"))
        rows.append({
            "strike": strike,
            "ce_key": c.get("instrument_key", ""), "pe_key": p.get("instrument_key", ""),
            "ce_ltp": ce_ltp, "ce_oi": ce_oi, "ce_prev_oi": ce_prev,
            "ce_vol": num(cm.get("volume")), "ce_close": ce_close, "ce_iv": num(cg.get("iv")), "ce_delta": num(cg.get("delta")),
            "ce_gamma": num(cg.get("gamma")), "ce_vega": num(cg.get("vega")), "ce_theta": num(cg.get("theta")),
            "ce_bid": num(cm.get("bid_price")), "ce_ask": num(cm.get("ask_price")),
            "ce_bid_qty": num(cm.get("bid_qty")), "ce_ask_qty": num(cm.get("ask_qty")),
            "pe_ltp": pe_ltp, "pe_oi": pe_oi, "pe_prev_oi": pe_prev,
            "pe_vol": num(pm.get("volume")), "pe_close": pe_close, "pe_iv": num(pg.get("iv")), "pe_delta": num(pg.get("delta")),
            "pe_gamma": num(pg.get("gamma")), "pe_vega": num(pg.get("vega")), "pe_theta": num(pg.get("theta")),
            "pe_bid": num(pm.get("bid_price")), "pe_ask": num(pm.get("ask_price")),
            "pe_bid_qty": num(pm.get("bid_qty")), "pe_ask_qty": num(pm.get("ask_qty")),
            "ce_doi_day": ce_oi - ce_prev, "pe_doi_day": pe_oi - pe_prev,
            "ce_prem_pct": ((ce_ltp / ce_close) - 1) * 100 if ce_close > 0 else 0,
            "pe_prem_pct": ((pe_ltp / pe_close) - 1) * 100 if pe_close > 0 else 0,
        })
    if not rows:
        return pd.DataFrame(columns=COLS)
    return pd.DataFrame(rows, columns=COLS).drop_duplicates("strike").sort_values("strike").reset_index(drop=True)


def classify(doi, prem):
    if doi > 0 and prem < -0.5: return "WRITING"
    if doi > 0 and prem > 0.5: return "LONG BUILD"
    if doi < 0 and prem > 0.5: return "SHORT COVER"
    if doi < 0 and prem < -0.5: return "UNWINDING"
    return "MIXED"


def norm_pos(s):
    s = pd.Series(s, dtype=float).replace([np.inf, -np.inf], np.nan).fillna(0)
    if len(s) == 0: return s
    mx = float(s.max())
    return s / mx if mx > 0 else pd.Series(np.zeros(len(s)), index=s.index)


def enrich_tick(df, index_name):
    df = df.copy()
    prev_key = f"pulse_prev_{index_name}"
    previous = st.session_state.get(prev_key, {})
    ce_tick, pe_tick = [], []
    for _, r in df.iterrows():
        old = previous.get(float(r.strike), {})
        ce_tick.append(float(r.ce_oi) - float(old.get("ce", r.ce_oi)))
        pe_tick.append(float(r.pe_oi) - float(old.get("pe", r.pe_oi)))
    st.session_state[prev_key] = {float(r.strike): {"ce": float(r.ce_oi), "pe": float(r.pe_oi)} for _, r in df.iterrows()}
    df["ce_doi_tick"] = ce_tick
    df["pe_doi_tick"] = pe_tick
    df["ce_state"] = [classify(a, b) for a, b in zip(df.ce_doi_day, df.ce_prem_pct)]
    df["pe_state"] = [classify(a, b) for a, b in zip(df.pe_doi_day, df.pe_prem_pct)]
    return df


def enrich_advanced(df, spot, step, index_name):
    d = df.copy()
    # Rolling session history is retained in session state, giving us OI acceleration and migration.
    hist_key = f"hist_{index_name}"
    hist = st.session_state.setdefault(hist_key, [])
    now = datetime.now(IST)
    snap = {float(r.strike): {"ce_oi": float(r.ce_oi), "pe_oi": float(r.pe_oi), "ce_ltp": float(r.ce_ltp), "pe_ltp": float(r.pe_ltp)} for _, r in d.iterrows()}
    hist.append((now, snap))
    cutoff = now - timedelta(minutes=45)
    st.session_state[hist_key] = [(t, s) for t, s in hist if t >= cutoff][-120:]
    hist = st.session_state[hist_key]

    def delta_minutes(strike, side, minutes):
        if not hist: return 0.0
        target = now - timedelta(minutes=minutes)
        prior = None
        for t, s in reversed(hist):
            if t <= target:
                prior = s.get(float(strike)); break
        if prior is None: return 0.0
        current = snap.get(float(strike), {})
        return current.get(side, 0.0) - prior.get(side, current.get(side, 0.0))

    d["ce_doi_5m"] = [delta_minutes(x, "ce_oi", 5) for x in d.strike]
    d["pe_doi_5m"] = [delta_minutes(x, "pe_oi", 5) for x in d.strike]
    d["ce_doi_15m"] = [delta_minutes(x, "ce_oi", 15) for x in d.strike]
    d["pe_doi_15m"] = [delta_minutes(x, "pe_oi", 15) for x in d.strike]
    d["ce_accel"] = d.ce_doi_tick - d.ce_doi_5m / 5.0
    d["pe_accel"] = d.pe_doi_tick - d.pe_doi_5m / 5.0
    d["ce_shift"] = d.ce_doi_5m
    d["pe_shift"] = d.pe_doi_5m
    d["ce_spread_pct"] = np.where(d.ce_ltp > 0, np.maximum(d.ce_ask - d.ce_bid, 0) / d.ce_ltp * 100, 0)
    d["pe_spread_pct"] = np.where(d.pe_ltp > 0, np.maximum(d.pe_ask - d.pe_bid, 0) / d.pe_ltp * 100, 0)
    d["ce_liquidity"] = np.minimum(100, 100 * (0.6*np.minimum(1, d.ce_vol / max(float(d.ce_vol.max()), 1)) + 0.4*np.maximum(0, 1-d.ce_spread_pct/3)))
    d["pe_liquidity"] = np.minimum(100, 100 * (0.6*np.minimum(1, d.pe_vol / max(float(d.pe_vol.max()), 1)) + 0.4*np.maximum(0, 1-d.pe_spread_pct/3)))
    d["ce_pressure"] = np.maximum(d.ce_doi_day, 0) * np.maximum(-d.ce_prem_pct, 0) + 0.5 * np.maximum(d.ce_doi_5m, 0)
    d["pe_pressure"] = np.maximum(d.pe_doi_day, 0) * np.maximum(-d.pe_prem_pct, 0) + 0.5 * np.maximum(d.pe_doi_5m, 0)
    d["ce_strength"] = 100 * (0.45 * norm_pos(np.log1p(d.ce_oi)) + 0.25 * norm_pos(np.maximum(d.ce_pressure, 0)) + 0.15 * norm_pos(np.maximum(d.ce_doi_5m, 0)) + 0.10 * np.exp(-abs(d.strike-spot)/(2.5*step)) + 0.05 * norm_pos(d.ce_liquidity))
    d["pe_strength"] = 100 * (0.45 * norm_pos(np.log1p(d.pe_oi)) + 0.25 * norm_pos(np.maximum(d.pe_pressure, 0)) + 0.15 * norm_pos(np.maximum(d.pe_doi_5m, 0)) + 0.10 * np.exp(-abs(d.strike-spot)/(2.5*step)) + 0.05 * norm_pos(d.pe_liquidity))
    return d


def pick_levels(d, spot, step, side, n=4):
    col = "ce_strength" if side == "resistance" else "pe_strength"
    src = d[d.strike >= spot] if side == "resistance" else d[d.strike <= spot]
    src = src.sort_values(col, ascending=False)
    out = []
    for _, r in src.iterrows():
        if all(abs(float(r.strike)-float(q.strike)) >= step*0.9 for q in out):
            out.append(r)
        if len(out) >= n: break
    return out


def calculate_levels(df, spot, step):
    if df.empty or spot <= 0: return None
    res = pick_levels(df, spot, step, "resistance")
    sup = pick_levels(df, spot, step, "support")
    eor = float(res[0].strike) if res else float(math.ceil(spot/step)*step)
    eos = float(sup[0].strike) if sup else float(math.floor(spot/step)*step)
    return {
        "eos": eos, "eos1": eos-step, "eor": eor, "eor1": eor+step,
        "support": sup, "resistance": res,
        "support_score": float(sup[0].pe_strength) if sup else 0,
        "resistance_score": float(res[0].ce_strength) if res else 0,
    }


def format_oi(x):
    x = float(x)
    if abs(x) >= 1e7: return f"{x/1e7:.2f} Cr"
    if abs(x) >= 1e5: return f"{x/1e5:.1f} L"
    if abs(x) >= 1e3: return f"{x/1e3:.1f} K"
    return f"{x:.0f}"


def sign_text(v):
    return f"{v:+,.0f}"


def strike_window(df, spot, step, n=19):
    if df.empty: return df
    return df.iloc[(df.strike-spot).abs().argsort()[:n]].sort_values("strike").copy()


def pcr_metrics(df, spot, step):
    x = df[(df.strike >= spot-5*step) & (df.strike <= spot+5*step)]
    ce, pe = x.ce_oi.sum(), x.pe_oi.sum()
    pcr = pe/ce if ce else np.nan
    dce, dpe = x.ce_doi_5m.sum(), x.pe_doi_5m.sum()
    return pcr, dce, dpe


def atm_metrics(df, spot, step):
    if df.empty: return {}
    atm_idx = (df.strike-spot).abs().idxmin()
    r = df.loc[atm_idx]
    straddle = r.ce_ltp + r.pe_ltp
    iv = np.nanmean([r.ce_iv, r.pe_iv])
    return {"strike": float(r.strike), "ce": float(r.ce_ltp), "pe": float(r.pe_ltp), "straddle": float(straddle), "iv": float(iv) if np.isfinite(iv) else np.nan}


def expected_move(df, spot):
    a = atm_metrics(df, spot, 1)
    return a.get("straddle", 0.0)


def level_state(r, side):
    if side == "support":
        oi, doi5, prem, state = r.pe_oi, r.pe_doi_5m, r.pe_prem_pct, r.pe_state
    else:
        oi, doi5, prem, state = r.ce_oi, r.ce_doi_5m, r.ce_prem_pct, r.ce_state
    if doi5 > 0 and prem < 0:
        return "BUILDING"
    if doi5 < 0:
        return "UNWINDING"
    return state


def survival_score(index_name, strike, side):
    events = st.session_state.get(f"level_events_{index_name}", {}).get(float(strike), {})
    return float(events.get(side, {}).get("reactions", 0))


def update_level_events(index_name, spot, levels, step):
    key = f"level_events_{index_name}"
    events = st.session_state.setdefault(key, {})
    for side, level in [("support", levels["eos"]), ("resistance", levels["eor"])]:
        e = events.setdefault(float(level), {"support": {"touches":0,"rejections":0,"reactions":0,"last":None}, "resistance": {"touches":0,"rejections":0,"reactions":0,"last":None}})[side]
        prev = e["last"]
        if prev is not None:
            if side == "support" and prev > level and spot <= level + 0.75*step:
                e["touches"] += 1
            if side == "resistance" and prev < level and spot >= level - 0.75*step:
                e["touches"] += 1
            if side == "support" and prev <= level + 0.75*step and spot > level + 0.5*step:
                e["rejections"] += 1
                e["reactions"] += 1
            if side == "resistance" and prev >= level - 0.75*step and spot < level - 0.5*step:
                e["rejections"] += 1
                e["reactions"] += 1
        e["last"] = spot
    return events


def price_oi_confirmation(r, side):
    if side == "support":
        doi, prem, state = r.pe_doi_5m, r.pe_prem_pct, r.pe_state
    else:
        doi, prem, state = r.ce_doi_5m, r.ce_prem_pct, r.ce_state
    if doi > 0 and prem < 0:
        return "CONFIRMED" if state == "WRITING" else "BUILDING"
    if doi < 0:
        return "AT RISK"
    return "MIXED"


def scenario_model(df, spot, levels, step, pcr, dce, dpe):
    if df.empty: return {"score":0,"primary":"WAIT","up":33,"range":34,"down":33,"reasons":[]}
    flow = float((levels["support_score"] - levels["resistance_score"]) / 2)
    breadth_proxy = 0.0
    if dpe > dce: breadth_proxy += 12
    elif dce > dpe: breadth_proxy -= 12
    position = 0
    if spot > levels["eor"]: position = 25
    elif spot < levels["eos"]: position = -25
    elif spot >= levels["eor"]-step*0.35: position = 8
    elif spot <= levels["eos"]+step*0.35: position = -8
    pcr_score = 0
    if np.isfinite(pcr): pcr_score = max(-12, min(12, (pcr-1.0)*35))
    score = max(-100, min(100, flow + breadth_proxy + position + pcr_score))
    up = int(round(33 + score*0.30))
    down = int(round(33 - score*0.30))
    rng = max(5, 100-up-down)
    # Normalize.
    total = up+down+rng
    up, rng, down = [int(round(v*100/total)) for v in (up,rng,down)]
    if score >= 25: primary = "UPSIDE"
    elif score <= -25: primary = "DOWNSIDE"
    else: primary = "RANGE / WAIT"
    reasons = []
    if levels["support_score"] > levels["resistance_score"]+8: reasons.append("PE support is stronger")
    if levels["resistance_score"] > levels["support_score"]+8: reasons.append("CE resistance is stronger")
    if dpe > dce*1.15: reasons.append("PE OI is building faster")
    if dce > dpe*1.15: reasons.append("CE OI is building faster")
    if np.isfinite(pcr) and pcr > 1.1: reasons.append("PCR above 1")
    if np.isfinite(pcr) and pcr < 0.9: reasons.append("PCR below 0.9")
    return {"score":score,"primary":primary,"up":up,"range":rng,"down":down,"reasons":reasons}


def state_machine(name, spot, levels, scenario):
    key = f"state_{name}"
    old = st.session_state.get(key, "RANGE")
    if spot > levels["eor1"]: new = "UPTREND / EXTENSION"
    elif spot > levels["eor"]: new = "BREAKOUT ATTEMPT"
    elif spot < levels["eos1"]: new = "DOWNTREND / EXTENSION"
    elif spot < levels["eos"]: new = "BREAKDOWN ATTEMPT"
    elif scenario["primary"] == "UPSIDE": new = "BULLISH RANGE"
    elif scenario["primary"] == "DOWNSIDE": new = "BEARISH RANGE"
    else: new = "RANGE"
    st.session_state[key] = new
    return old, new


def migration_text(df, spot, step):
    below = df[df.strike <= spot].copy()
    above = df[df.strike >= spot].copy()
    if len(below) < 2 or len(above) < 2: return "No clear migration yet."
    p1 = below.sort_values("pe_strength", ascending=False).iloc[0]
    p2 = below.sort_values("pe_strength", ascending=False).iloc[1]
    c1 = above.sort_values("ce_strength", ascending=False).iloc[0]
    c2 = above.sort_values("ce_strength", ascending=False).iloc[1]
    parts=[]
    if p1.pe_strength > p2.pe_strength*1.08 and p1.strike < p2.strike: parts.append(f"PUT support migrating lower toward {int(p1.strike)}")
    elif p1.strike > p2.strike: parts.append(f"PUT support concentrated higher at {int(p1.strike)}")
    if c1.strike < c2.strike: parts.append(f"CALL resistance concentrated lower at {int(c1.strike)}")
    elif c1.strike > c2.strike: parts.append(f"CALL resistance concentrated higher at {int(c1.strike)}")
    return " • ".join(parts) if parts else "No strong migration signal."


def oi_heatmap(df, spot, step, levels=None):
    """Real visual OI heatmap rendered as HTML inside an isolated component."""
    levels = levels or {}
    x = strike_window(df, spot, step, 17).copy()
    if x.empty:
        st.info("Option-chain heatmap unavailable.")
        return

    x["strike"] = pd.to_numeric(x["strike"], errors="coerce")
    x = x.dropna(subset=["strike"]).sort_values("strike")
    ce = pd.to_numeric(x.get("ce_oi", 0), errors="coerce").fillna(0)
    pe = pd.to_numeric(x.get("pe_oi", 0), errors="coerce").fillna(0)
    cd = pd.to_numeric(x.get("ce_doi_5m", 0), errors="coerce").fillna(0)
    pd_ = pd.to_numeric(x.get("pe_doi_5m", 0), errors="coerce").fillna(0)
    cmax, pmax = max(float(ce.max()),1), max(float(pe.max()),1)

    def alpha(v, mx):
        return 0.08 + 0.76*min(1,max(0,float(v)/mx))
    def fmt(v): return format_oi(float(v))
    def shift(v):
        v=float(v)
        return ("↑" if v>0 else "↓" if v<0 else "—") + (f" {fmt(abs(v))}" if abs(v)>=1 else "")
    def tag(strike):
        tags=[]
        if abs(strike-spot) <= step*.45: tags.append(("ATM","atm"))
        if abs(strike-float(levels.get("eos", -1e12))) <= step*.45: tags.append(("EOS","eos"))
        if abs(strike-float(levels.get("eor", 1e12))) <= step*.45: tags.append(("EOR","eor"))
        return " ".join(f'<span class="tag {c}">{t}</span>' for t,c in tags)

    rows=[]
    for i,(_,r) in enumerate(x.iterrows()):
        strike=float(r["strike"]); cv=float(r.get("ce_oi",0) or 0); pv=float(r.get("pe_oi",0) or 0)
        cdelta=float(r.get("ce_doi_5m",0) or 0); pdelta=float(r.get("pe_doi_5m",0) or 0)
        atm=abs(strike-spot)<=step*.45
        rowcls=" focus" if atm else ""
        rows.append(f"""
        <div class="hm-row{rowcls}">
          <div class="hm-side ce">
            <div class="bar" style="width:{max(3,cv/cmax*100):.1f}%;background:linear-gradient(90deg,rgba(239,68,68,.10),rgba(220,38,38,{alpha(cv,cmax):.2f}))"></div>
            <div class="val">{fmt(cv)}</div><div class="doi {'up' if cdelta>0 else 'down' if cdelta<0 else 'flat'}">{shift(cdelta)}</div>
          </div>
          <div class="strike"><b>{int(strike):,}</b>{tag(strike)}</div>
          <div class="hm-side pe">
            <div class="bar" style="width:{max(3,pv/pmax*100):.1f}%;background:linear-gradient(90deg,rgba(5,150,105,{alpha(pv,pmax):.2f}),rgba(16,185,129,.10))"></div>
            <div class="val">{fmt(pv)}</div><div class="doi {'up' if pdelta>0 else 'down' if pdelta<0 else 'flat'}">{shift(pdelta)}</div>
          </div>
        </div>""")
    html=f"""<!doctype html><html><head><style>
    *{{box-sizing:border-box}}body{{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;background:#fff;color:#172033}}
    .card{{border:1px solid #e4e8ef;border-radius:18px;overflow:hidden;background:#fff;box-shadow:0 6px 24px rgba(15,23,42,.06)}}
    .head{{display:grid;grid-template-columns:1fr 120px 1fr;background:#f8fafc;border-bottom:1px solid #e4e8ef;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#64748b}}
    .head div{{padding:12px 16px}}.ceh{{text-align:right;color:#b42318}}.peh{{color:#047857}}
    .hm-row{{display:grid;grid-template-columns:1fr 120px 1fr;min-height:52px;border-bottom:1px solid #eef1f5}}
    .hm-row:last-child{{border-bottom:0}}.hm-row.focus{{background:#f7fafc;box-shadow:inset 0 2px 0 #64748b,inset 0 -2px 0 #64748b}}
    .hm-side{{position:relative;display:flex;align-items:center;gap:9px;padding:7px 14px;overflow:hidden}}
    .hm-side.ce{{justify-content:flex-end;text-align:right;border-right:1px solid #eef1f5}}.hm-side.pe{{border-left:1px solid #eef1f5}}
    .bar{{position:absolute;top:5px;bottom:5px;border-radius:7px;z-index:0}}.ce .bar{{right:8px}}.pe .bar{{left:8px}}
    .val,.doi{{position:relative;z-index:1}}.val{{font-size:14px;font-weight:800}}.doi{{font-size:11px;font-weight:700;min-width:52px}}
    .up{{color:#15803d}}.down{{color:#b91c1c}}.flat{{color:#94a3b8}}
    .strike{{display:flex;flex-direction:column;align-items:center;justify-content:center;background:#fff;border-left:1px solid #e8ebf0;border-right:1px solid #e8ebf0;gap:4px}}
    .strike b{{font-size:14px}}.tag{{font-size:8px;font-weight:900;padding:2px 6px;border-radius:999px;letter-spacing:.06em}}
    .atm{{background:#e2e8f0;color:#334155}}.eos{{background:#dcfce7;color:#166534}}.eor{{background:#fee2e2;color:#b91c1c}}
    .legend{{display:flex;gap:18px;flex-wrap:wrap;padding:10px 14px;background:#fbfcfe;border-top:1px solid #eef1f5;font-size:10px;color:#64748b}}
    .legend b{{color:#334155}}.dot{{font-weight:900}}.red{{color:#b91c1c}}.green{{color:#047857}}
    </style></head><body><div class="card">
    <div class="head"><div class="ceh">CALL OI / ΔOI</div><div style="text-align:center">STRIKE</div><div class="peh">PUT OI / ΔOI</div></div>
    {''.join(rows)}
    <div class="legend"><span><span class="dot red">●</span> CE resistance</span><span><span class="dot green">●</span> PE support</span><span><b>↑</b> building</span><span><b>↓</b> unwinding</span><span><b>ATM</b> spot area</span><span><b>EOS/EOR</b> model levels</span></div>
    </div></body></html>"""
    components.html(html, height=60+len(rows)*52+52, scrolling=False)


def option_chain_display(df, spot, step):
    x = strike_window(df, spot, step, 21)
    if x.empty: return
    out = pd.DataFrame({
        "CE OI":[format_oi(v) for v in x.ce_oi],
        "CE ΔOI 5m":[sign_text(v) for v in x.ce_doi_5m],
        "CE ΔOI day":[sign_text(v) for v in x.ce_doi_day],
        "CE State":x.ce_state,
        "CE LTP":x.ce_ltp.round(2),
        "CE Bid":x.ce_bid.round(2),
        "CE Ask":x.ce_ask.round(2),
        "CE IV":(x.ce_iv*100).round(1),
        "STRIKE":x.strike.astype(int),
        "PE IV":(x.pe_iv*100).round(1),
        "PE Bid":x.pe_bid.round(2),
        "PE Ask":x.pe_ask.round(2),
        "PE LTP":x.pe_ltp.round(2),
        "PE State":x.pe_state,
        "PE ΔOI day":[sign_text(v) for v in x.pe_doi_day],
        "PE ΔOI 5m":[sign_text(v) for v in x.pe_doi_5m],
        "PE OI":[format_oi(v) for v in x.pe_oi],
    })
    st.dataframe(out, use_container_width=True, hide_index=True, height=650)


def level_table(rows, side):
    out=[]
    for r in rows:
        if side=="support":
            out.append({"Level":int(r.strike),"Score":f"{r.pe_strength:.0f}","PE OI":format_oi(r.pe_oi),"ΔOI 5m":sign_text(r.pe_doi_5m),"PE LTP":f"₹{r.pe_ltp:.2f}","Spread %":f"{r.pe_spread_pct:.2f}","Read":level_state(r,"support"),"Price/OI":price_oi_confirmation(r,"support")})
        else:
            out.append({"Level":int(r.strike),"Score":f"{r.ce_strength:.0f}","CE OI":format_oi(r.ce_oi),"ΔOI 5m":sign_text(r.ce_doi_5m),"CE LTP":f"₹{r.ce_ltp:.2f}","Spread %":f"{r.ce_spread_pct:.2f}","Read":level_state(r,"resistance"),"Price/OI":price_oi_confirmation(r,"resistance")})
    return pd.DataFrame(out)


def resolve_stock_quotes(token, symbols):
    keys = ",".join([f"NSE_EQ|{sym}" for sym in symbols])
    result=[]
    try:
        data=ltp_quotes(token, keys)
        for sym in symbols:
            key=f"NSE_EQ|{sym}"
            q=quote_from_data(data,key)
            px=num(q.get("last_price")); cp=num(q.get("cp"))
            if px>0:
                result.append({"symbol":sym,"price":px,"cp":cp,"move":(px/cp-1)*100 if cp else 0})
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(result)


def load_weights():
    up = st.session_state.get("uploaded_weights")
    if up is not None:
        try:
            d=pd.read_csv(up)
            cols={c.lower():c for c in d.columns}
            s=cols.get("symbol"); w=cols.get("weight_pct") or cols.get("weight")
            if s and w:
                return dict(zip(d[s].astype(str).str.upper(), d[w].astype(float)))
        except Exception:
            pass
    return None


def render_contributors(token, name):
    weights = load_weights() or (NIFTY_WEIGHTS if name=="NIFTY 50" else BANK_WEIGHTS)
    symbols=list(weights.keys())
    # Limit REST work but still capture the dominant names first; user can upload exact weights.
    syms=symbols
    df=resolve_stock_quotes(token, syms)
    if df.empty:
        st.warning("Stock-flow quotes unavailable right now. The OI engine remains active.")
        return
    df["weight"] = df.symbol.map(weights).fillna(0)
    df["impact"] = df.weight*df.move/100
    df["side"] = np.where(df.impact>0,"PUSHING HIGHER","DRAGGING LOWER")
    adv=int((df.move>0).sum()); dec=int((df.move<0).sum())
    st.session_state[f"breadth_proxy_{name}"]=float((adv-dec)/max(len(df),1))
    weighted=df.impact.sum();
    top_up=df[df.impact>0].sort_values("impact",ascending=False).head(7)
    top_dn=df[df.impact<0].sort_values("impact").head(7)
    top3_share=(top_up.impact.sum()/df[df.impact>0].impact.sum()) if (df.impact>0).any() and df[df.impact>0].impact.sum()!=0 else 0
    quality="BROAD" if (adv>=len(df)*.65 or dec>=len(df)*.65) and top3_share<0.60 else "NARROW" if top3_share>=0.60 else "MIXED"
    a,b,c=st.columns(3); a.metric("Net weighted pressure",f"{weighted:+.3f}%"); b.metric("Breadth (tracked)",f"{adv}/{len(df)} up"); c.metric("Participation", quality)
    if quality=="NARROW": st.warning("⚠️ Narrow index move: a small group of heavyweights is carrying most of the tracked pressure.")
    l,r=st.columns(2)
    with l:
        st.markdown("### 🟢 Pushing the index higher")
        st.dataframe(top_up[["symbol","weight","move","impact"]].rename(columns={"symbol":"Stock","weight":"Weight %","move":"Move %","impact":"Index impact %"}).round(3),use_container_width=True,hide_index=True)
    with r:
        st.markdown("### 🔴 Dragging the index lower")
        st.dataframe(top_dn[["symbol","weight","move","impact"]].rename(columns={"symbol":"Stock","weight":"Weight %","move":"Move %","impact":"Index impact %"}).round(3),use_container_width=True,hide_index=True)
    st.caption("Reference weights are a dated snapshot unless you upload the latest index weight CSV. Nifty 50 uses free-float market-cap weighting; Bank Nifty also uses free-float market-cap methodology. Source: NSE Indices.")



def session_market_metrics(token, key):
    """Price-structure metrics from the live intraday 1-minute series."""
    try:
        d = intraday_index_stats(token, key)
        # Re-fetch through the same cached helper for VWAP and richer session stats.
        raw = api_get3(f"/historical-candle/intraday/{quote(key, safe='')}/minutes/1", token)
        candles = ((raw.get("data") or {}).get("candles") or []) if isinstance(raw, dict) else []
        rows = []
        for c in candles:
            if len(c) < 5:
                continue
            rows.append({
                "ts": c[0], "open": num(c[1]), "high": num(c[2]),
                "low": num(c[3]), "close": num(c[4]), "vol": num(c[5]) if len(c) > 5 else 0
            })
        x = pd.DataFrame(rows).sort_values("ts") if rows else pd.DataFrame()
        if x.empty:
            return d
        typical = (x.high + x.low + x.close) / 3
        vol = x.vol.fillna(0)
        vwap = float((typical * vol).sum() / vol.sum()) if vol.sum() > 0 else float(x.close.iloc[-1])
        first15 = x.iloc[:15] if len(x) >= 15 else x
        return {
            **d,
            "vwap": vwap,
            "session_high": float(x.high.max()),
            "session_low": float(x.low.min()),
            "or_high": float(first15.high.max()),
            "or_low": float(first15.low.min()),
            "bars": len(x),
            "candles": x[["ts","open","high","low","close","vol"]].values.tolist(),
        }
    except Exception:
        return d if isinstance(d, dict) else {}


@st.cache_data(ttl=15, show_spinner=False)
def previous_day_levels(token, key):
    """Best-effort previous daily candle. Failure is non-fatal."""
    try:
        d = api_get3(f"/historical-candle/{quote(key, safe='')}/day/1", token)
        candles = ((d.get("data") or {}).get("candles") or []) if isinstance(d, dict) else []
        if len(candles) < 2:
            return {}
        rows = []
        for c in candles:
            if len(c) >= 5:
                rows.append({"ts": c[0], "open": num(c[1]), "high": num(c[2]), "low": num(c[3]), "close": num(c[4])})
        x = pd.DataFrame(rows).sort_values("ts")
        if len(x) < 2:
            return {}
        r = x.iloc[-2]
        return {"prev_high": float(r.high), "prev_low": float(r.low), "prev_close": float(r.close)}
    except Exception:
        return {}


def max_pain_level(df):
    if df.empty:
        return np.nan
    strikes = df.strike.to_numpy(dtype=float)
    ce = df.ce_oi.to_numpy(dtype=float)
    pe = df.pe_oi.to_numpy(dtype=float)
    pains = []
    for k in strikes:
        call_pain = np.sum(ce * np.maximum(k - strikes, 0))
        put_pain = np.sum(pe * np.maximum(strikes - k, 0))
        pains.append(call_pain + put_pain)
    return float(strikes[int(np.argmin(pains))]) if pains else np.nan


def option_structure_metrics(df, spot, step):
    if df.empty:
        return {}
    core = df[(df.strike >= spot - 8*step) & (df.strike <= spot + 8*step)].copy()
    if core.empty:
        core = df.copy()
    ce_oi, pe_oi = core.ce_oi.sum(), core.pe_oi.sum()
    ce_doi, pe_doi = core.ce_doi_5m.sum(), core.pe_doi_5m.sum()
    ce_day, pe_day = core.ce_doi_day.sum(), core.pe_doi_day.sum()
    pcr = pe_oi / ce_oi if ce_oi else np.nan
    pcr5 = (pe_doi / ce_doi) if ce_doi > 0 else np.nan

    atm_i = (core.strike - spot).abs().idxmin()
    atm = core.loc[atm_i]
    atm_iv = np.nanmean([atm.ce_iv, atm.pe_iv])
    # 25-delta skew proxy: closest absolute delta to 0.25 on each wing.
    call25 = core.iloc[(core.ce_delta - 0.25).abs().argsort()[:1]]
    put25 = core.iloc[(core.pe_delta + 0.25).abs().argsort()[:1]]
    c25 = float(call25.ce_iv.iloc[0]) if not call25.empty else np.nan
    p25 = float(put25.pe_iv.iloc[0]) if not put25.empty else np.nan

    # Gross gamma concentration. OI does not reveal dealer positioning, so this is
    # explicitly a gross gamma concentration proxy, not dealer GEX.
    if "ce_gamma" in core.columns:
        gamma_proxy = float(np.nansum(np.abs(core.ce_gamma) * core.ce_oi) +
                            np.nansum(np.abs(core.pe_gamma) * core.pe_oi))
    else:
        gamma_proxy = 0.0

    return {
        "pcr": float(pcr) if np.isfinite(pcr) else np.nan,
        "pcr5": float(pcr5) if np.isfinite(pcr5) else np.nan,
        "ce_oi": float(ce_oi), "pe_oi": float(pe_oi),
        "ce_doi": float(ce_doi), "pe_doi": float(pe_doi),
        "ce_day": float(ce_day), "pe_day": float(pe_day),
        "atm_strike": float(atm.strike),
        "atm_straddle": float(atm.ce_ltp + atm.pe_ltp),
        "atm_iv": float(atm_iv) if np.isfinite(atm_iv) else np.nan,
        "iv_skew_25d": (p25 - c25) if np.isfinite(p25) and np.isfinite(c25) else np.nan,
        "max_pain": max_pain_level(core),
        "gamma_proxy": gamma_proxy,
    }


def price_acceptance_score(spot, level, side, momentum, volume_context=0.0):
    """Score whether price is accepting outside a level, not merely crossing it."""
    if side == "up":
        dist = spot - level
    else:
        dist = level - spot
    # 0 at level, positive beyond level.
    base = max(-1.0, min(1.0, dist / max(abs(level) * 0.0008, 1.0)))
    mom = max(-1.0, min(1.0, momentum / 0.25))
    return int(round(50 + 35*base + 15*mom + volume_context))


def level_context(df, spot, levels, step):
    """Turn raw level math into trader-readable state without pretending certainty."""
    out = {}
    for label, side, level in [
        ("EOR", "resistance", levels["eor"]),
        ("EOS", "support", levels["eos"]),
    ]:
        row = df.loc[(df.strike - level).abs().idxmin()] if not df.empty else None
        if row is None:
            continue
        state = level_state(row, side)
        strength = float(row.ce_strength if side == "resistance" else row.pe_strength)
        shift = float(row.ce_doi_5m if side == "resistance" else row.pe_doi_5m)
        prem = float(row.ce_prem_pct if side == "resistance" else row.pe_prem_pct)
        out[label] = {
            "level": float(level), "strength": strength, "state": state,
            "shift": shift, "premium": prem
        }
    return out


def signal_quality(score, data_quality, scenario_spread):
    """Confidence-like quality, deliberately separated from a win probability."""
    q = 50 + abs(score)*0.28 + scenario_spread*0.18 + (data_quality - 50)*0.35
    return int(max(0, min(100, round(q))))


def trade_map(name, spot, levels, scenario, structure, market, quality):
    primary = scenario["primary"]
    if primary == "UPSIDE":
        trigger = levels["eor"]
        target = levels["eor1"]
        invalid = levels["eor"]
        condition = "Price acceptance above EOR + CE OI unwinding / PE OI building"
        bias = "Upside scenario"
    elif primary == "DOWNSIDE":
        trigger = levels["eos"]
        target = levels["eos1"]
        invalid = levels["eos"]
        condition = "Price acceptance below EOS + PE OI unwinding / CE OI building"
        bias = "Downside scenario"
    else:
        trigger = levels["eor"]
        target = levels["eos"]
        invalid = None
        condition = "Wait for acceptance outside the EOS/EOR band"
        bias = "Range / no clear edge"
    return {
        "bias": bias, "trigger": trigger, "target": target, "invalidation": invalid,
        "condition": condition, "quality": quality
    }


def detect_market_phase():
    t = datetime.now(IST).time()
    if t < datetime.strptime("09:30", "%H:%M").time():
        return "OPENING / PRICE DISCOVERY"
    if t < datetime.strptime("11:30", "%H:%M").time():
        return "MORNING TREND / RANGE"
    if t < datetime.strptime("13:30", "%H:%M").time():
        return "MIDDAY / COMPRESSION"
    if t < datetime.strptime("15:00", "%H:%M").time():
        return "AFTERNOON EXPANSION"
    return "CLOSE / SQUARE-OFF"


def data_quality_score(df, spot, expiry):
    if df.empty or spot <= 0:
        return 0
    valid = df[(df.ce_oi > 0) | (df.pe_oi > 0)]
    coverage = min(1.0, len(valid) / 15)
    atm = df.loc[(df.strike - spot).abs().idxmin()] if not df.empty else None
    atm_ok = 1.0 if atm is not None and (atm.ce_ltp > 0 or atm.pe_ltp > 0) else 0.0
    expiry_ok = 1.0 if expiry else 0.0
    return int(round(100 * (0.55*coverage + 0.35*atm_ok + 0.10*expiry_ok)))


def scenario_model_v3(df, spot, levels, step, pcr, dce, dpe, market, structure):
    """Transparent multi-factor scenario score. It is a scenario classifier, not a guarantee."""
    if df.empty:
        return {"score": 0, "primary": "WAIT", "up": 33, "range": 34, "down": 33, "reasons": []}

    score = 0.0
    reasons = []

    # OI structure: 35%
    level_bias = (levels["support_score"] - levels["resistance_score"]) * 0.38
    score += level_bias
    if level_bias > 8: reasons.append("support structure is stronger")
    if level_bias < -8: reasons.append("resistance structure is stronger")

    # OI shift: 20%
    shift = max(-20, min(20, (dpe - dce) / max(abs(dpe)+abs(dce), 1) * 20))
    score += shift
    if shift > 7: reasons.append("PE OI is building faster")
    if shift < -7: reasons.append("CE OI is building faster")

    # Price momentum + VWAP: 20%
    r5 = float(market.get("ret5", 0))
    r15 = float(market.get("ret15", 0))
    mom = max(-18, min(18, r5*7 + r15*2.5))
    if market.get("vwap", 0):
        if spot > market["vwap"]: mom += 4
        elif spot < market["vwap"]: mom -= 4
    score += max(-20, min(20, mom))
    if mom > 8: reasons.append("price momentum is positive")
    if mom < -8: reasons.append("price momentum is negative")

    # PCR: 10%
    if np.isfinite(pcr):
        pcr_score = max(-10, min(10, (pcr - 1.0)*25))
        score += pcr_score

    # ATM / skew / volatility: 15%
    atm_pressure = max(-8, min(8, (dpe - dce) / max(abs(dpe)+abs(dce), 1) * 8))
    score += atm_pressure
    skew = structure.get("iv_skew_25d", np.nan)
    if np.isfinite(skew):
        # Positive put-minus-call IV skew = more downside protection demand.
        score += max(-5, min(5, -skew*8))

    score = float(max(-100, min(100, score)))

    # Probability-like display is explicitly scenario weight, not historical win rate.
    up_raw = 34 + score*0.30
    down_raw = 34 - score*0.30
    range_raw = max(8, 100 - up_raw - down_raw)
    vals = np.array([max(1, up_raw), max(1, range_raw), max(1, down_raw)], dtype=float)
    vals = vals / vals.sum() * 100
    up, rng, down = [int(round(v)) for v in vals]
    if up + rng + down != 100:
        rng += 100 - (up + rng + down)

    if score >= 25:
        primary = "UPSIDE"
    elif score <= -25:
        primary = "DOWNSIDE"
    else:
        primary = "RANGE / WAIT"

    return {
        "score": score, "primary": primary, "up": up, "range": rng, "down": down,
        "reasons": reasons
    }


def option_chain_download(df, name, expiry):
    if df.empty:
        return
    cols = [c for c in df.columns if c not in {"ce_state","pe_state"}]
    payload = df[cols].to_csv(index=False).encode()
    st.download_button(
        f"Download {name} option-chain snapshot",
        payload,
        file_name=f"{name.replace(' ','_').lower()}_{expiry}_oi_snapshot.csv",
        mime="text/csv",
        key=f"download_chain_{name}"
    )



@st.cache_data(ttl=30, show_spinner=False)
def search_futures(token, name):
    """Find the nearest active index future using Upstox Instrument Search."""
    q = "NIFTY" if name == "NIFTY 50" else "BANKNIFTY"
    try:
        d = api_get("/instruments/search", token, {
            "query": q, "exchanges": "NSE", "segments": "FO",
            "instrument_types": "FUT", "expiry": "current_month",
            "page_number": 1, "records": 30,
        })
        rows = d.get("data", []) if isinstance(d, dict) else []
        key = INDEXES[name]["key"]
        rows = [r for r in rows if isinstance(r, dict) and r.get("underlying_key") == key]
        if not rows:
            return {}
        rows.sort(key=lambda r: str(r.get("expiry", "9999-99-99")))
        return rows[0]
    except Exception:
        return {}


@st.cache_data(ttl=4, show_spinner=False)
def futures_context(token, name, spot):
    contract = search_futures(token, name)
    if not contract:
        return {"available": False, "reason": "No current-month index future found."}
    key = contract.get("instrument_key")
    try:
        data = ltp_quotes(token, key)
        q = quote_from_data(data, key)
        fut = num(q.get("last_price"))
        cp = num(q.get("cp"))
        # Market quote LTP does not always expose OI; use OI endpoint as a second source.
        oi = num(q.get("oi"))
        poi = num(q.get("poi"))
        if oi == 0:
            try:
                od = api_get("/market/quote/ltp", token, {"instrument_key": key})
                qq = quote_from_data(od.get("data", {}) if isinstance(od, dict) else {}, key)
                oi = num(qq.get("oi"), oi); poi = num(qq.get("poi"), poi)
            except Exception:
                pass
        basis = fut - spot if fut else 0.0
        basis_pct = basis / spot * 100 if spot else 0.0
        return {
            "available": fut > 0, "key": key, "symbol": contract.get("trading_symbol", ""),
            "expiry": contract.get("expiry", ""), "ltp": fut, "cp": cp, "oi": oi,
            "poi": poi, "doi": oi-poi, "basis": basis, "basis_pct": basis_pct,
        }
    except Exception as e:
        return {"available": False, "reason": str(e), "symbol": contract.get("trading_symbol", "")}


def volume_profile_metrics(market, spot, bins=32):
    """Approximate session volume profile from 1-minute candles."""
    try:
        candles = market.get("candles", [])
        if not candles:
            return {}
        x = pd.DataFrame(candles, columns=["ts","open","high","low","close","vol"]).copy()
        x = x.dropna(subset=["high","low","close"]).copy()
        if x.empty:
            return {}
        lo, hi = float(x.low.min()), float(x.high.max())
        if hi <= lo:
            return {"poc": float(x.close.iloc[-1]), "vah": float(hi), "val": float(lo)}
        edges = np.linspace(lo, hi, bins + 1)
        idx = np.clip(np.digitize(x.close, edges) - 1, 0, bins - 1)
        vol = x.vol.fillna(0).to_numpy(dtype=float)
        profile = np.bincount(idx, weights=vol, minlength=bins)
        total = profile.sum()
        poc_i = int(np.argmax(profile))
        target = total * 0.70
        order = np.argsort(profile)[::-1]
        cum = 0.0; chosen=[]
        for i in order:
            chosen.append(int(i)); cum += profile[i]
            if cum >= target: break
        val_i, vah_i = min(chosen), max(chosen)
        centers = (edges[:-1] + edges[1:]) / 2
        return {"poc": float(centers[poc_i]), "val": float(edges[val_i]), "vah": float(edges[vah_i+1]), "total_volume": float(total)}
    except Exception:
        return {}


def confluence_engine(df, spot, levels, step, market, prev, structure):
    """Score levels by independent evidence; avoids double-counting raw OI."""
    vp = volume_profile_metrics(market, spot)
    out = {}
    for label, side, level in [("EOR","resistance",levels["eor"]),("EOS","support",levels["eos"]),("EOR+1","resistance",levels["eor1"]),("EOS-1","support",levels["eos1"])]:
        score = 0.0; reasons=[]
        # OI level score (already combines concentration + fresh shift + liquidity)
        row = df.loc[(df.strike-level).abs().idxmin()] if not df.empty else None
        if row is not None:
            oi_score = float(row.ce_strength if side=="resistance" else row.pe_strength)
            score += 0.35 * oi_score
            if oi_score >= 80: reasons.append("strong OI wall")
            doi = float(row.ce_doi_5m if side=="resistance" else row.pe_doi_5m)
            prem = float(row.ce_prem_pct if side=="resistance" else row.pe_prem_pct)
            if doi > 0 and prem < 0: score += 10; reasons.append("fresh writing")
            if doi < 0: score -= 7; reasons.append("OI unwinding")
        # Previous-day structure
        if prev:
            for k, tag in [("prev_high","previous high"),("prev_low","previous low"),("prev_close","previous close")]:
                if abs(level-prev.get(k,1e18)) <= step*0.6:
                    score += 10; reasons.append(tag)
        # Volume profile confluence
        if vp:
            for k, tag in [("poc","POC"),("vah","VAH"),("val","VAL")]:
                if abs(level-vp.get(k,1e18)) <= step*0.6:
                    score += 9; reasons.append(tag)
        # VWAP / opening range
        vwap = market.get("vwap",0)
        if vwap and abs(level-vwap) <= step*0.6:
            score += 8; reasons.append("VWAP")
        for k, tag in [("or_high","opening-range high"),("or_low","opening-range low")]:
            z=market.get(k,0)
            if z and abs(level-z)<=step*0.6:
                score += 8; reasons.append(tag)
        out[label] = {"score": int(max(0,min(100,round(score)))), "reasons": reasons, "vp": vp}
    return out


def detect_absorption_failed_breakout(name, spot, levels, market):
    key=f"price_events_{name}"
    hist=st.session_state.setdefault(key, [])
    now=datetime.now(IST)
    hist.append((now, float(spot)))
    hist[:] = [(t,p) for t,p in hist if t >= now-timedelta(minutes=30)][-300:]
    if len(hist)<3:
        return {"absorption":"NO DATA","failed_breakout":"NO DATA","rejections":0}
    prices=np.array([p for _,p in hist],dtype=float)
    result={"absorption":"NONE","failed_breakout":"NONE","rejections":0}
    band=max(levels["eor"]-levels["eos"],1)
    # Repeated tests near a boundary without meaningful follow-through.
    for side,level in [("EOR",levels["eor"]),("EOS",levels["eos"])]:
        near=np.abs(prices-level)<=max(band*0.08, 0.35)
        if near.sum()>=3:
            if side=="EOR" and prices[-1] < level and prices.max() >= level:
                result["absorption"]="POSSIBLE EOR ABSORPTION"
                result["rejections"]=int(near.sum())
            elif side=="EOS" and prices[-1] > level and prices.min() <= level:
                result["absorption"]="POSSIBLE EOS ABSORPTION"
                result["rejections"]=int(near.sum())
    # Failed breakout: crossed a boundary and returned inside the band.
    if len(prices)>=4:
        prev=prices[:-1]
        if prev.max() > levels["eor"] and spot < levels["eor"]:
            result["failed_breakout"]="FAILED EOR BREAKOUT"
        if prev.min() < levels["eos"] and spot > levels["eos"]:
            result["failed_breakout"]="FAILED EOS BREAKDOWN"
    return result


def regime_engine(spot, levels, market, structure, futures, events):
    score=0; labels=[]
    vwap=market.get("vwap",0)
    r5=market.get("ret5",0); r15=market.get("ret15",0)
    if spot>levels["eor"]: score+=25; labels.append("above EOR")
    elif spot<levels["eos"]: score-=25; labels.append("below EOS")
    if vwap:
        score += 10 if spot>vwap else -10; labels.append("above VWAP" if spot>vwap else "below VWAP")
    score += max(-20,min(20,r5*10+r15*2))
    if futures.get("available"):
        score += max(-10,min(10,futures.get("basis_pct",0)*30))
    iv=structure.get("atm_iv",np.nan)
    if np.isfinite(iv):
        if iv > 0.18: labels.append("high IV")
        elif iv < 0.10: labels.append("low IV")
    failed=events.get("failed_breakout","NONE")
    if failed.startswith("FAILED"):
        score *= 0.55; labels.append("failed-breakout risk")
    if score>=35: regime="TREND UP"
    elif score<=-35: regime="TREND DOWN"
    elif abs(score)<12: regime="RANGE / MEAN REVERSION"
    elif score>0: regime="BULLISH TRANSITION"
    else: regime="BEARISH TRANSITION"
    return {"regime":regime,"score":int(max(-100,min(100,round(score)))),"labels":labels}


def live_feature_weights():
    """Evidence-first policy: experimental features have zero live weight until promoted by OOS tests."""
    if not st.session_state.get("evidence_first", True):
        return DEFAULT_FEATURE_WEIGHTS.copy(), "EXPLORATORY"
    promoted=st.session_state.get("promoted_features", {})
    if not promoted:
        return {k:0.0 for k in FEATURE_REGISTRY}, "CORE ONLY — NO EXPERIMENTAL FEATURES PROMOTED"
    return {k:float(promoted.get(k,0.0)) for k in FEATURE_REGISTRY}, "EVIDENCE-GATED"


def enhanced_scenario(df, spot, levels, step, pcr, dce, dpe, market, structure, futures, confluence, regime, events, breadth_score=0.0, feature_weights=None):
    weights=feature_weights or DEFAULT_FEATURE_WEIGHTS
    raw={k:0.0 for k in FEATURE_REGISTRY}
    raw["confluence"]=(confluence["EOS"]["score"]-confluence["EOR"]["score"])/100
    raw["futures_basis"]=max(-1,min(1,futures.get("basis_pct",0)*25)) if futures.get("available") else 0
    raw["absorption"]=-0.75 if events.get("failed_breakout","NONE").startswith("FAILED EOR") else 0.75 if events.get("failed_breakout","NONE").startswith("FAILED EOS") else 0
    raw["regime"]=regime.get("score",0)/100
    vp=volume_profile_metrics(market,spot)
    if vp:
        # Price above VAH is bullish, below VAL bearish.
        raw["volume_profile"]=1 if spot>vp["vah"] else -1 if spot<vp["val"] else 0
    raw["atm_pressure"]=max(-1,min(1,(dpe-dce)/max(abs(dpe)+abs(dce),1)))
    skew=structure.get("iv_skew_25d",np.nan)
    raw["iv_skew"]=-max(-1,min(1,skew*5)) if np.isfinite(skew) else 0
    raw["breadth"]=max(-1,min(1,breadth_score))
    raw["vwap"]=1 if market.get("vwap",0) and spot>market["vwap"] else -1 if market.get("vwap",0) else 0
    orh,orl=market.get("or_high",0),market.get("or_low",0)
    raw["opening_range"]=1 if orh and spot>orh else -1 if orl and spot<orl else 0
    # OI structure remains the anchor; new features are overlays, not replacements.
    base=(levels["support_score"]-levels["resistance_score"])/100 + (dpe-dce)/max(abs(dpe)+abs(dce),1)*0.45
    score=base*55 + sum(weights[k]*raw[k]*45 for k in raw)
    if np.isfinite(pcr): score += max(-8,min(8,(pcr-1)*20))
    score=max(-100,min(100,score))
    up=34+score*0.28; down=34-score*0.28; rng=max(10,100-up-down)
    vals=np.array([max(1,up),max(1,rng),max(1,down)],dtype=float); vals=vals/vals.sum()*100
    up,rng,down=[int(round(v)) for v in vals]
    if up+rng+down!=100: rng += 100-(up+rng+down)
    if score>=28: primary="UPSIDE"
    elif score<=-28: primary="DOWNSIDE"
    else: primary="RANGE / WAIT"
    reasons=[]
    ranked=sorted(((abs(raw[k]*weights[k]),k,raw[k]) for k in raw),reverse=True)[:5]
    for _,k,v in ranked:
        if abs(v)>=0.25: reasons.append(f"{FEATURE_REGISTRY[k]['label']}: {'bullish' if v>0 else 'bearish'}")
    if events.get("failed_breakout","NONE")!="NONE": reasons.append(events["failed_breakout"])
    return {"score":float(score),"primary":primary,"up":up,"range":rng,"down":down,"reasons":reasons,"raw_features":raw}


def simple_walk_forward(df, target_col, feature_cols, min_train=30):
    """Dependency-free expanding-window logistic model for research, never for live orders."""
    d=df.copy().replace([np.inf,-np.inf],np.nan).dropna(subset=[target_col])
    feature_cols=[c for c in feature_cols if c in d.columns]
    if len(d)<min_train+10 or not feature_cols:
        return {"ok":False,"reason":"Need more rows and valid feature columns."}
    X=d[feature_cols].fillna(0).astype(float).to_numpy(); y=(d[target_col].astype(float)>0).astype(float).to_numpy()
    preds=[]; actual=[]
    for i in range(min_train,len(d)):
        trX=X[:i]; trY=y[:i]; teX=X[i:i+1]
        mu=trX.mean(0); sd=trX.std(0); sd[sd<1e-9]=1
        z=(trX-mu)/sd; tz=(teX-mu)/sd
        w=np.zeros(z.shape[1]); b=0.0
        for _ in range(120):
            p=1/(1+np.exp(np.clip(-(z@w+b),-40,40)))
            grad_w=z.T@(p-trY)/len(trY)+0.01*w
            grad_b=float(np.mean(p-trY))
            w-=0.08*grad_w; b-=0.08*grad_b
        pr=float(1/(1+np.exp(np.clip(-(tz@w+b),-40,40)))[0])
        preds.append(pr); actual.append(y[i])
    pp=np.array(preds); aa=np.array(actual); hit=((pp>=0.5)==(aa>=0.5)).mean()
    brier=np.mean((pp-aa)**2)
    return {"ok":True,"rows":len(d),"oos_rows":len(pp),"hit_rate":float(hit),"brier":float(brier),"predictions":pp,"actual":aa}



@st.cache_data(ttl=60, show_spinner=False)
def official_market_intel(token, key, expiry):
    """Use Upstox's dedicated market-information endpoints as an independent cross-check."""
    today=datetime.now(IST).date().isoformat()
    out={}
    try:
        d=api_get("/market/change-oi",token,{"instrument_key":key,"expiry":expiry,"date":today,"interval":1})
        out["change_oi"]=(d.get("data") or {}) if isinstance(d,dict) else {}
    except Exception as e: out["change_oi_error"]=str(e)
    try:
        d=api_get("/market/max-pain",token,{"instrument_key":key,"expiry":expiry,"date":today,"bucket_interval":30})
        out["max_pain"]=(d.get("data") or {}) if isinstance(d,dict) else {}
    except Exception as e: out["max_pain_error"]=str(e)
    try:
        d=api_get("/market/pcr",token,{"instrument_key":key,"expiry":expiry,"date":today,"bucket_interval":30})
        out["pcr"]=(d.get("data") or {}) if isinstance(d,dict) else {}
    except Exception as e: out["pcr_error"]=str(e)
    return out


@st.cache_data(ttl=20, show_spinner=False)
def smartlist_radar(token):
    rows=[]
    for cat in ["OI_GAINERS","OI_LOSERS","PRICE_GAINERS","PRICE_LOSERS"]:
        try:
            d=api_get("/market/smartlist/futures",token,{"asset_type":"INDEX","category":cat,"page_number":1,"page_size":10})
            for r in (d.get("data") or [])[:10]:
                if isinstance(r,dict):
                    r=dict(r); r["category"]=cat; rows.append(r)
        except Exception:
            continue
    return rows


def render_smartlist_radar(token):
    rows=smartlist_radar(token)
    if not rows:
        return
    st.markdown("## 📡 Index Futures Radar")
    d=pd.DataFrame(rows)
    preferred=[c for c in ["trading_symbol","symbol","name","price","open_interest","volume_traded_today","metric_key","category"] if c in d.columns]
    st.dataframe(d[preferred].head(20),use_container_width=True,hide_index=True)
    st.caption("Upstox Smartlist ranks index futures by live market signals such as OI and price categories. It is a radar, not a trade signal.")


def feature_gate_panel():
    st.markdown("## 🧪 Feature Gate — evidence before permanence")
    st.caption("Policy: a feature is promoted into the live scenario score only when it improves out-of-sample evidence. Otherwise it stays visible for research but contributes zero live weight.")
    template=pd.DataFrame([{"timestamp":"2026-08-14 09:30:00","target_return_30m":0.25, **{k:0.0 for k in FEATURE_REGISTRY}}])
    st.download_button("Download research CSV template",template.to_csv(index=False).encode(),"feature_research_template.csv","text/csv",key="feature_template")
    up=st.file_uploader("Upload time-ordered research rows",type=["csv"],key="feature_gate_csv")
    if up is None:
        st.info("No historical research file loaded. Live mode stays **core-only** under the evidence-first policy.")
        return
    try:
        d=pd.read_csv(up)
        target="target_return_30m" if "target_return_30m" in d.columns else "future_return"
        cols=[c for c in FEATURE_REGISTRY if c in d.columns]
        if target not in d.columns:
            st.error("CSV needs target_return_30m (or future_return).")
            return
        baseline=[c for c in ["vwap","opening_range"] if c in cols]
        if len(d)<60:
            st.warning("At least ~60 ordered rows are recommended before promoting anything. More dates/regimes are much better.")
        base=simple_walk_forward(d,target,baseline,min_train=max(30,min(80,len(d)//3))) if baseline else {"ok":False}
        base_hit=base.get("hit_rate",0) if base.get("ok") else 0
        results=[]
        for feature in cols:
            test_cols=list(dict.fromkeys(baseline+[feature]))
            r=simple_walk_forward(d,target,test_cols,min_train=max(30,min(80,len(d)//3)))
            if r.get("ok"):
                results.append({"feature":feature,"label":FEATURE_REGISTRY[feature]["label"],"OOS hit":r["hit_rate"],"Brier":r["brier"],"delta_vs_baseline":r["hit_rate"]-base_hit})
        if not results:
            st.error("Not enough valid feature/target data for an OOS test.")
            return
        res=pd.DataFrame(results).sort_values("delta_vs_baseline",ascending=False)
        st.dataframe(res.style.format({"OOS hit":"{:.1%}","Brier":"{:.4f}","delta_vs_baseline":"{:+.2%}"}),use_container_width=True,hide_index=True)
        # Conservative promotion gate: positive OOS improvement AND non-worsening Brier.
        promoted=res[(res["delta_vs_baseline"]>0.01) & (res["Brier"] <= res["Brier"].median())]
        st.write(f"**Promotion candidates:** {len(promoted)}. Gate requires >1 percentage-point OOS hit-rate improvement and Brier no worse than the cross-feature median.")
        if st.button("Promote passing features to live model",key="promote_features"):
            st.session_state["promoted_features"]={r.feature:float(DEFAULT_FEATURE_WEIGHTS.get(r.feature,0.05)) for _,r in promoted.iterrows()}
            st.success("Promoted: " + (", ".join(promoted.feature.tolist()) if len(promoted) else "none"))
        if st.session_state.get("promoted_features"):
            st.write("**Currently promoted:** " + ", ".join(st.session_state["promoted_features"].keys()))
        st.caption("This gate is intentionally conservative. A feature should also be checked for false-break rate, MFE/MAE, drawdown, costs/slippage and stability across multiple dates and regimes before being considered production-grade.")
    except Exception as e:
        st.error(f"Research file error: {e}")


class LiveFeedCache:
    def __init__(self, token):
        self.token=token; self.lock=threading.Lock(); self.data={}; self.status="starting"; self.error=""; self.streamer=None; self.thread=None; self.keys=[]
    def _normalize(self, message):
        if isinstance(message,dict): return message
        try:
            from google.protobuf.json_format import MessageToDict
            if hasattr(message,"DESCRIPTOR"):
                return MessageToDict(message, preserving_proto_field_name=True)
        except Exception:
            pass
        if hasattr(message,"to_dict"):
            try: return message.to_dict()
            except Exception: pass
        return {}
    def _on_message(self,message):
        obj=self._normalize(message)
        feeds=obj.get("feeds",{}) if isinstance(obj,dict) else {}
        if not feeds: return
        with self.lock:
            for k,v in feeds.items(): self.data[k]=v
            self.status="connected"
    def start(self, keys):
        keys=sorted(set(k for k in keys if k))
        if not keys: return
        with self.lock:
            if self.thread and self.thread.is_alive():
                add=[k for k in keys if k not in self.keys]
                if add and self.streamer:
                    try: self.streamer.subscribe(add,"full")
                    except Exception: pass
                self.keys=sorted(set(self.keys+keys)); return
            self.keys=keys
        def runner():
            try:
                import upstox_client
                cfg=upstox_client.Configuration(); cfg.access_token=self.token
                self.streamer=upstox_client.MarketDataStreamerV3(upstox_client.ApiClient(cfg), self.keys, "full")
                self.streamer.on("message", self._on_message)
                try: self.streamer.auto_reconnect(True,5,10)
                except Exception: pass
                self.status="connecting"
                self.streamer.connect()
            except Exception as e:
                self.status="fallback"; self.error=str(e)
        self.thread=threading.Thread(target=runner,daemon=True)
        self.thread.start()
    def snapshot(self):
        with self.lock: return dict(self.data), self.status, self.error

@st.cache_resource(show_spinner=False)
def live_feed_resource(token):
    return LiveFeedCache(token)


def ws_extract(feed):
    """Best-effort extraction from SDK dict/protobuf-converted V3 feed."""
    found={}
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():
                lk=str(k).lower()
                if lk in {"ltp","cp","oi","poi","atp","vtt","tbq","tsq"} and isinstance(v,(int,float,str)):
                    found[lk]=num(v)
                elif isinstance(v,(dict,list)):
                    walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(feed)
    return found


def websocket_pulse(token, keys):
    if not st.session_state.get("use_ws", True):
        return {},"disabled","WebSocket disabled in sidebar"
    try:
        cache=live_feed_resource(token); cache.start(keys); data,status,error=cache.snapshot()
        return data,status,error
    except Exception as e:
        return {},"fallback",str(e)

def auto_record_snapshot(name, spot, levels, scenario, market, structure, futures, regime, events):
    """Persist one compact model state per pulse so future outcomes can be computed later."""
    key="auto_snapshots"
    rows=st.session_state.setdefault(key,[])
    now=datetime.now(IST)
    rows.append({
        "timestamp":now.strftime("%Y-%m-%d %H:%M:%S"), "index":name, "spot":float(spot),
        "eos":float(levels["eos"]), "eor":float(levels["eor"]), "model":float(scenario["score"]),
        "up_scenario":int(scenario["up"]), "range_scenario":int(scenario["range"]), "down_scenario":int(scenario["down"]),
        "ret5":float(market.get("ret5",0)), "ret15":float(market.get("ret15",0)),
        "pcr":float(structure.get("pcr",np.nan)), "iv_skew":float(structure.get("iv_skew_25d",np.nan)),
        "futures_basis_pct":float(futures.get("basis_pct",0)), "futures_oi":float(futures.get("oi",0)),
        "regime":regime.get("regime",""), "failed_break":1 if events.get("failed_breakout","NONE")!="NONE" else 0,
    })
    # Keep memory bounded for long browser sessions.
    st.session_state[key]=rows[-5000:]


def render_auto_backtest():
    st.markdown("## 📚 Auto-captured Session Research")
    rows=st.session_state.get("auto_snapshots",[])
    if not rows:
        st.info("No automatic snapshots yet. The live terminal records model states during refreshes.")
        return
    d=pd.DataFrame(rows)
    st.metric("Captured states",len(d))
    st.download_button("Download raw model snapshots",d.to_csv(index=False).encode(),"intraday_model_snapshots.csv","text/csv",key="download_auto_snapshots")
    if len(d)<20:
        st.caption("Keep the terminal running across multiple sessions. A few intraday snapshots are not enough for OOS validation.")
    # Same-session forward outcomes where possible. These are research labels only.
    d["ts_dt"]=pd.to_datetime(d.timestamp)
    results=[]
    for idx,row in d.iterrows():
        later=d[(d.index==idx) | (d.ts_dt>row.ts_dt)] if False else d[d.ts_dt>row.ts_dt]
        later=later[later["index"]==row["index"]]
        if later.empty: continue
        for mins,label in [(5,"future_return_5m"),(15,"future_return_15m"),(30,"future_return_30m")]:
            target=row.ts_dt+pd.Timedelta(minutes=mins)
            q=later.iloc[(later.ts_dt-target).abs().argsort()[:1]]
            if not q.empty:
                fut=float(q.spot.iloc[0]); results.append({**row.to_dict(),"horizon":label,"future_return":(fut/row.spot-1)*100})
    if results:
        r=pd.DataFrame(results)
        r["win"]=(r.model*r.future_return>0).astype(int)
        g=r.groupby("horizon").agg(rows=("win","size"),hit_rate=("win","mean"),mean_return=("future_return","mean")).reset_index()
        st.dataframe(g.style.format({"hit_rate":"{:.1%}","mean_return":"{:+.3f}%"}),use_container_width=True,hide_index=True)
        st.caption("Auto-captured outcomes are only useful when snapshots span multiple market days. Same-session results are descriptive, not a production backtest.")




def intraday_setup_engine(name, spot, levels, market, structure, futures, events, regime, scenario, df, step):
    """Convert the analytical engine into a concrete, testable intraday setup."""
    primary = scenario.get("primary","RANGE / WAIT")
    eor, eos = float(levels["eor"]), float(levels["eos"])
    vwap = float(market.get("vwap",0) or 0)
    r5, r15 = float(market.get("ret5",0) or 0), float(market.get("ret15",0) or 0)
    failed = str(events.get("failed_breakout","NONE"))
    absorption = str(events.get("absorption","NONE"))
    spot_dist_eor, spot_dist_eos = spot-eor, spot-eos

    setup="NO TRADE"
    direction="WAIT"
    trigger=stop=target=None
    reasons=[]

    # Setup classification: structure first, then confirmation.
    if failed.startswith("FAILED EOR"):
        setup="EOR FAILED BREAKOUT"; direction="DOWN"
        trigger=eor; stop=eor+step*0.5; target=eos
        reasons.append("EOR breakout failed")
    elif failed.startswith("FAILED EOS"):
        setup="EOS FAILED BREAKDOWN"; direction="UP"
        trigger=eos; stop=eos-step*0.5; target=eor
        reasons.append("EOS breakdown failed")
    elif spot > eor and primary=="UPSIDE":
        setup="EOR BREAKOUT"; direction="UP"
        trigger=eor; stop=eor-step*0.5; target=levels["eor1"]
        reasons.append("price above EOR")
    elif spot < eos and primary=="DOWNSIDE":
        setup="EOS BREAKDOWN"; direction="DOWN"
        trigger=eos; stop=eos+step*0.5; target=levels["eos1"]
        reasons.append("price below EOS")
    elif vwap and spot > vwap and r5 > 0 and r15 >= 0 and primary=="UPSIDE":
        setup="VWAP TREND / PULLBACK"; direction="UP"
        trigger=spot; stop=max(eos, vwap-step*0.25); target=eor if spot < eor else levels["eor1"]
        reasons.append("price above VWAP with positive momentum")
    elif vwap and spot < vwap and r5 < 0 and r15 <= 0 and primary=="DOWNSIDE":
        setup="VWAP TREND / PULLBACK"; direction="DOWN"
        trigger=spot; stop=min(eor, vwap+step*0.25); target=eos if spot > eos else levels["eos1"]
        reasons.append("price below VWAP with negative momentum")
    elif eos < spot < eor:
        setup="RANGE / WAIT"; direction="WAIT"
        reasons.append("price inside EOS/EOR band")
    else:
        setup="TRANSITION / WAIT"; direction="WAIT"
        reasons.append("structure and momentum are not aligned")

    quality=float(scenario.get("score",0))
    conf=0
    if vwap and ((direction=="UP" and spot>vwap) or (direction=="DOWN" and spot<vwap)): conf+=15
    if futures.get("available"):
        b=float(futures.get("basis",0) or 0)
        if (direction=="UP" and b>0) or (direction=="DOWN" and b<0): conf+=15
    dce=float(structure.get("ce_doi",0) or 0); dpe=float(structure.get("pe_doi",0) or 0)
    if (direction=="UP" and dpe>dce) or (direction=="DOWN" and dce>dpe): conf+=20
    if "FAILED" not in failed: conf+=15
    if regime.get("regime","").startswith(("TREND","BULLISH","BEARISH")): conf+=15
    if direction=="UP" and r5>0: conf+=10
    if direction=="DOWN" and r5<0: conf+=10
    setup_score=int(max(0,min(100,50+conf+(abs(quality)-25)*0.35)))

    rr=None
    if trigger is not None and stop is not None and target is not None:
        risk=abs(trigger-stop); reward=abs(target-trigger)
        rr=reward/risk if risk else None

    # Trade guard: reject setups with poor structure even if directional score is high.
    guard=[]
    if direction=="WAIT": guard.append("Wait for a level acceptance/rejection.")
    if rr is not None and rr < 1.25: guard.append("R/R below 1.25 — not attractive.")
    if "FAILED" not in failed and "FAILED" in absorption.upper(): guard.append("Absorption risk is active.")
    if setup_score < 58: guard.append("Confirmation is too weak.")
    no_trade = bool(guard) or direction=="WAIT"

    return {
        "setup":setup, "direction":direction, "trigger":trigger, "stop":stop,
        "target":target, "rr":rr, "score":setup_score, "no_trade":no_trade,
        "reasons":reasons, "guard":guard, "failed":failed, "absorption":absorption
    }


def level_lifecycle(df, spot, levels, step):
    """Classify EOS/EOR and nearby OI walls as fresh, tested, weakening, broken or flipped."""
    out=[]
    for label, strike, side, oi_col, doi_col in [
        ("EOR", levels["eor"], "CE", "ce_oi", "ce_doi_5m"),
        ("EOS", levels["eos"], "PE", "pe_oi", "pe_doi_5m"),
    ]:
        row=df.iloc[(df["strike"]-strike).abs().argsort()[:1]]
        if row.empty: continue
        r=row.iloc[0]
        oi=float(r.get(oi_col,0) or 0); doi=float(r.get(doi_col,0) or 0)
        if label=="EOR":
            if spot > strike+step*0.35: state="BROKEN / ABOVE"
            elif spot >= strike-step*0.35 and doi < -max(oi*0.01,1): state="WEAKENING"
            else: state="ACTIVE"
        else:
            if spot < strike-step*0.35: state="BROKEN / BELOW"
            elif spot <= strike+step*0.35 and doi < -max(oi*0.01,1): state="WEAKENING"
            else: state="ACTIVE"
        out.append((label,strike,side,state,oi,doi))
    return out


def liquidity_warning(df, spot, step):
    x=strike_window(df,spot,step,3)
    vals=[]
    for _,r in x.iterrows():
        for side in ("ce","pe"):
            bid=float(r.get(f"{side}_bid",0) or 0); ask=float(r.get(f"{side}_ask",0) or 0)
            ltp=float(r.get(f"{side}_ltp",0) or 0)
            if bid>0 and ask>0 and ltp>0:
                spread=ask-bid
                spread_pct=spread/ltp*100
                vals.append((spread_pct,side,int(r.strike),spread))
    if not vals: return {"status":"UNKNOWN","text":"Bid/ask unavailable around ATM."}
    worst=max(vals); avg=sum(v[0] for v in vals)/len(vals)
    if worst[0] > 2.5: status="CAUTION"
    elif avg > 1.2: status="WATCH"
    else: status="OK"
    return {"status":status,"text":f"ATM option spread avg {avg:.2f}% · widest {worst[0]:.2f}% at {worst[2]:,} {worst[1].upper()}"}


def gamma_iv_pressure(df, spot, step):
    x=strike_window(df,spot,step,9).copy()
    rows=[]
    for _,r in x.iterrows():
        cg=float(r.get("ce_gamma",0) or 0); pg=float(r.get("pe_gamma",0) or 0)
        co=float(r.get("ce_oi",0) or 0); po=float(r.get("pe_oi",0) or 0)
        civ=float(r.get("ce_iv",0) or 0); piv=float(r.get("pe_iv",0) or 0)
        gamma=(abs(cg)*co + abs(pg)*po)
        iv=(civ*co+piv*po)/(co+po) if co+po else 0
        rows.append((int(r.strike),gamma,iv))
    rows=sorted(rows,key=lambda z:z[1],reverse=True)
    return rows[:5]


def render_intraday_intelligence(name, spot, levels, market, structure, futures, events, regime, scenario, df, step):
    setup=intraday_setup_engine(name,spot,levels,market,structure,futures,events,regime,scenario,df,step)
    life=level_lifecycle(df,spot,levels,step)
    liq=liquidity_warning(df,spot,step)
    gamma=gamma_iv_pressure(df,spot,step)

    st.markdown("## 🧭 Intraday setup intelligence")
    a,b,c,d=st.columns(4)
    a.metric("Current setup",setup["setup"])
    b.metric("Setup quality",f'{setup["score"]}/100')
    c.metric("Execution", "⚪ NO TRADE" if setup["no_trade"] else "🟢 TRADEABLE")
    d.metric("R/R", f'{setup["rr"]:.2f}:1' if setup["rr"] is not None else "—")

    x1,x2=st.columns([1.25,1])
    with x1:
        st.markdown("### What has to happen?")
        if setup["trigger"] is not None:
            st.write(f"**Trigger:** {setup['trigger']:,.0f}")
            st.write(f"**Target:** {setup['target']:,.0f}")
            st.write(f"**Invalidation:** {setup['stop']:,.0f}")
        else:
            st.write("Wait for clean acceptance/rejection outside the decision zone.")
        for r in setup["reasons"][:3]: st.write("🟢 "+r)
        for g in setup["guard"][:3]: st.write("⚠️ "+g)
    with x2:
        st.markdown("### Level lifecycle")
        for label,strike,side,state,oi,doi in life:
            icon="🟢" if state.startswith("ACTIVE") else "🟡" if state=="WEAKENING" else "🔴"
            st.write(f"{icon} **{label} {strike:,.0f}** · {state} · ΔOI {sign_text(doi)}")

    st.markdown("### Confirmation matrix")
    cols=st.columns(5)
    items=[
        ("Regime",regime.get("regime","—"),regime.get("score",0)),
        ("VWAP", "CONFIRM" if ((spot>market.get("vwap",0))==(scenario.get("score",0)>0)) else "DIVERGE", 1),
        ("OI", "PE building" if structure.get("pe_doi",0)>structure.get("ce_doi",0) else "CE building", structure.get("pe_doi",0)-structure.get("ce_doi",0)),
        ("Futures","CONFIRM" if futures.get("available") else "UNAVAILABLE",futures.get("basis",0)),
        ("Liquidity",liq["status"],0)
    ]
    for col,(lab,val,_) in zip(cols,items):
        with col:
            col.metric(lab,str(val)[:28])

    with st.expander("📈 Volatility & gamma map", expanded=False):
        if gamma:
            st.dataframe(pd.DataFrame(gamma,columns=["Strike","OI-weighted gamma proxy","OI-weighted IV"]).round(4),use_container_width=True,hide_index=True)
        st.caption("Gamma is an OI-weighted proxy from available option Greeks; it is not dealer GEX.")
        st.write("Liquidity:",liq["text"])

    # A simple multi-timeframe alignment score using available session returns.
    r5=float(market.get("ret5",0) or 0); r15=float(market.get("ret15",0) or 0)
    direction=1 if scenario.get("score",0)>0 else -1 if scenario.get("score",0)<0 else 0
    aligned=sum([direction!=0 and r5*direction>0, direction!=0 and r15*direction>0])
    st.markdown(f"**Multi-timeframe alignment:** {aligned}/2  ·  5m {r5:+.2f}%  ·  15m {r15:+.2f}%")
    if setup["no_trade"]:
        st.warning("NO TRADE: the engine does not have enough aligned evidence or acceptable R/R for a clean setup.")
    else:
        st.success(f"TRADEABLE CONDITION: wait for the trigger at {setup['trigger']:,.0f} and respect {setup['stop']:,.0f} invalidation.")



def trader_oi_battlefield(df, spot, step, levels):
    """Simple visual OI battlefield. Raw chain remains in Quant Details."""
    x = strike_window(df, spot, step, 17).copy()
    if x.empty:
        st.info("Option-chain battlefield unavailable.")
        return

    st.caption("Visual pressure map • darker = larger OI • ↑ = building • ↓ = unwinding • ATM / EOS / EOR are decision anchors")
    oi_heatmap(df, spot, step, levels)

    above=x[x["strike"]>=spot].copy()
    below=x[x["strike"]<=spot].copy()
    res=above.nlargest(3,"ce_oi")
    sup=below.nlargest(3,"pe_oi")
    a,b=st.columns(2)
    with a:
        st.markdown("**🔴 CALL WALLS — resistance**")
        for _,r in res.iterrows():
            st.write(f"**{int(r.strike):,}**  ·  {format_oi(r.ce_oi)} OI  ·  ΔOI {sign_text(r.ce_doi_5m)}")
    with b:
        st.markdown("**🟢 PUT WALLS — support**")
        for _,r in sup.iterrows():
            st.write(f"**{int(r.strike):,}**  ·  {format_oi(r.pe_oi)} OI  ·  ΔOI {sign_text(r.pe_doi_5m)}")

def render_index_v3(name, token):
    """Trader-first presentation layer over the existing V4 analytics engine."""
    cfg = INDEXES[name]
    try:
        spot, cp = underlying_ltp(token, cfg["key"])
        contracts = option_contracts(token, cfg["key"])
        expiry = nearest_expiry(contracts)
        if not expiry:
            st.error(f"{name}: no active option expiry returned by Upstox.")
            return
        chain = option_chain(token, cfg["key"], expiry)
        df = enrich_tick(build_option_df(chain), name)
    except Exception as e:
        st.error(f"{name}: {e}")
        return

    if df.empty:
        st.error(f"{name}: no usable option strikes returned for {expiry}.")
        return

    df = enrich_advanced(df, spot, cfg["step"], name)
    levels = calculate_levels(df, spot, cfg["step"])
    if levels is None:
        st.error(f"{name}: unable to calculate EOS/EOR from the returned chain.")
        return

    market = session_market_metrics(token, cfg["key"])
    prev = previous_day_levels(token, cfg["key"])
    structure = option_structure_metrics(df, spot, cfg["step"])
    pcr = structure.get("pcr", np.nan)
    dce, dpe = structure.get("ce_doi", 0), structure.get("pe_doi", 0)
    futures = futures_context(token, name, spot)
    official = official_market_intel(token, cfg["key"], expiry)
    events = detect_absorption_failed_breakout(name, spot, levels, market)
    confluence = confluence_engine(df, spot, levels, cfg["step"], market, prev, structure)
    regime = regime_engine(spot, levels, market, structure, futures, events)
    breadth_proxy = float(st.session_state.get(f"breadth_proxy_{name}", 0.0))
    live_weights, gate_status = live_feature_weights()
    scenario = enhanced_scenario(
        df, spot, levels, cfg["step"], pcr, dce, dpe, market, structure,
        futures, confluence, regime, events, breadth_proxy, live_weights
    )
    exploratory = enhanced_scenario(
        df, spot, levels, cfg["step"], pcr, dce, dpe, market, structure,
        futures, confluence, regime, events, breadth_proxy, DEFAULT_FEATURE_WEIGHTS
    )

    auto_record_snapshot(name, spot, levels, scenario, market, structure, futures, regime, events)

    dq = data_quality_score(df, spot, expiry)
    spread = max(scenario["up"], scenario["down"]) - scenario["range"]
    quality = signal_quality(scenario["score"], dq, spread)
    phase = detect_market_phase()
    change_pct = (spot / cp - 1) * 100 if cp else 0
    vwap = market.get("vwap", 0)

    vix, vixcp = 0, 0
    try:
        vix, vixcp = underlying_ltp(token, VIX_KEY)
    except Exception:
        pass
    vix_move = (vix / vixcp - 1) * 100 if vixcp else 0

    update_level_events(name, spot, levels, cfg["step"])
    old_state, new_state = state_machine(name, spot, levels, scenario)
    ctx = level_context(df, spot, levels, cfg["step"])
    vp = volume_profile_metrics(market, spot)
    atm = atm_metrics(df, spot, cfg["step"])
    expected = atm.get("straddle", 0)

    # -----------------------------
    # HERO: 10-second trader read
    # -----------------------------
    primary = scenario["primary"]
    score = float(scenario.get("score", 0))
    if primary == "UPSIDE":
        state_icon, state_label, cls = "🟢", "BULLISH", "bull"
    elif primary == "DOWNSIDE":
        state_icon, state_label, cls = "🔴", "BEARISH", "bear"
    else:
        state_icon, state_label, cls = "🟡", "RANGE / WAIT", "range"

    st.markdown(f"## {name} <span style='font-size:12px;color:#64748b;font-weight:500'>• {expiry} • {phase} • refreshed every few seconds</span>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class="trader-shell">
      <div class="decision">
        <div class="box {cls}">
          <div class="label">Market state</div>
          <div class="big">{state_icon} {state_label}</div>
          <div class="sub">Primary scenario • {abs(score):.0f}/100</div>
        </div>
        <div class="box">
          <div class="label">Spot</div><div class="big">{spot:,.2f}</div>
          <div class="sub">{change_pct:+.2f}% today</div>
        </div>
        <div class="box">
          <div class="label">Decision quality</div><div class="big">{quality}/100</div>
          <div class="sub">Data quality {dq}/100</div>
        </div>
        <div class="box">
          <div class="label">Scenario</div><div class="big" style="font-size:19px">↑ {scenario['up']}% · ↔ {scenario['range']}% · ↓ {scenario['down']}%</div>
          <div class="sub">Evidence-first: {gate_status}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="mini-grid">
      <div class="mini"><div class="k">VWAP</div><div class="v">{vwap:,.0f} {'↑' if spot>vwap else '↓'}</div></div>
      <div class="mini"><div class="k">Opening range</div><div class="v">{market.get('or_low',0):,.0f}–{market.get('or_high',0):,.0f}</div></div>
      <div class="mini"><div class="k">Session H/L</div><div class="v">{market.get('session_low',0):,.0f}–{market.get('session_high',0):,.0f}</div></div>
      <div class="mini"><div class="k">Futures basis</div><div class="v">{futures.get('basis',0):+.1f}</div></div>
      <div class="mini"><div class="k">PCR</div><div class="v">{pcr:.2f}</div></div>
      <div class="mini"><div class="k">India VIX</div><div class="v">{vix:.2f}</div></div>
      <div class="mini"><div class="k">5m</div><div class="v">{market.get('ret5',0):+.2f}%</div></div>
      <div class="mini"><div class="k">15m</div><div class="v">{market.get('ret15',0):+.2f}%</div></div>
    </div>
    """, unsafe_allow_html=True)

    # -----------------------------
    # WHY + KEY LEVELS

    # -----------------------------
    w1, w2 = st.columns([1.15, 1.0])
    with w1:
        st.markdown("## 🧠 Why is the model leaning this way?")
        reasons = []
        if dpe > dce:
            reasons.append("🟢 Put OI is building faster than call OI in the core chain.")
        elif dce > dpe:
            reasons.append("🔴 Call OI is building faster than put OI in the core chain.")
        if vwap:
            reasons.append(("🟢" if spot > vwap else "🔴") + f" Price is {abs(spot-vwap):,.0f} points " + ("above" if spot > vwap else "below") + " VWAP.")
        if futures.get("available"):
            fb = futures.get("basis", 0)
            reasons.append(("🟢" if (fb >= 0 and score >= 0) or (fb <= 0 and score <= 0) else "⚠️") +
                           f" Futures basis is {fb:+.1f}; " +
                           ("confirming" if (fb >= 0 and score >= 0) or (fb <= 0 and score <= 0) else "diverging") + ".")
        if events.get("absorption") not in (None, "", "NONE"):
            reasons.append("⚠️ " + str(events.get("absorption")))
        if events.get("failed_breakout") not in (None, "", "NONE"):
            reasons.append("⚠️ " + str(events.get("failed_breakout")))
        if not reasons:
            reasons.append("🟡 No single factor has a strong edge yet.")
        for r in reasons[:5]:
            st.write(r)

    with w2:
        st.markdown("## 🎯 Key levels")
        st.markdown(f"""
        <div class="level-stack">
          <div class="lvl ext redlvl"><span>EOR + 1</span><b>{levels["eor1"]:,.0f}</b><small>extension</small></div>
          <div class="lvl redlvl"><span>EOR</span><b>{levels["eor"]:,.0f}</b><small>resistance · {levels["resistance_score"]:.0f}/100</small></div>
          <div class="lvl spotlvl"><span>SPOT</span><b>{spot:,.2f}</b><small>current price</small></div>
          <div class="lvl greenlvl"><span>EOS</span><b>{levels["eos"]:,.0f}</b><small>support · {levels["support_score"]:.0f}/100</small></div>
          <div class="lvl ext greenlvl"><span>EOS − 1</span><b>{levels["eos1"]:,.0f}</b><small>extension</small></div>
        </div>
        """, unsafe_allow_html=True)

    # -----------------------------
    # NEXT MOVE CARD
    # -----------------------------
    st.markdown("## 🔮 Next move — condition, target & invalidation")
    n1, n2, n3 = st.columns(3)
    with n1:
        if primary == "UPSIDE":
            st.markdown("### 🟢 UPSIDE")
            st.write(f"**Trigger:** acceptance above **{levels['eor']:,.0f}**")
            st.write(f"**Target:** **{levels['eor1']:,.0f}**")
            st.write(f"**Invalidation:** back below **{levels['eor']-cfg['step']*0.5:,.0f}**")
        elif primary == "DOWNSIDE":
            st.markdown("### 🔴 DOWNSIDE")
            st.write(f"**Trigger:** acceptance below **{levels['eos']:,.0f}**")
            st.write(f"**Target:** **{levels['eos1']:,.0f}**")
            st.write(f"**Invalidation:** back above **{levels['eos']+cfg['step']*0.5:,.0f}**")
        else:
            st.markdown("### 🟡 RANGE / WAIT")
            st.write("**Trigger:** clean acceptance outside EOS/EOR")
            st.write("**Target:** next extension level")
            st.write("**Invalidation:** return into the band")
    with n2:
        st.markdown("### Confirmation checklist")
        checks = [
            ("Price vs VWAP", vwap and ((spot > vwap and score > 0) or (spot < vwap and score < 0))),
            ("Futures", futures.get("available") and (((futures.get("basis",0) >= 0) and score >= 0) or ((futures.get("basis",0) <= 0) and score <= 0))),
            ("OI direction", (dpe > dce and score > 0) or (dce > dpe and score < 0)),
            ("No failed breakout", events.get("failed_breakout","NONE") == "NONE"),
        ]
        for label, ok in checks:
            st.write(("🟢" if ok else "⚪") + f" {label}")
    with n3:
        st.markdown("### Setup quality")
        st.metric("Decision quality", f"{quality}/100")
        if quality >= 75:
            st.success("High-quality structure")
        elif quality >= 55:
            st.warning("Tradable only with confirmation")
        else:
            st.info("No clear edge — wait")

    # -----------------------------
    # INTRADAY SETUP INTELLIGENCE
    # -----------------------------
    render_intraday_intelligence(name, spot, levels, market, structure, futures, events, regime, scenario, df, cfg["step"])

    # -----------------------------
    # LAST PULSE
    # -----------------------------
    st.markdown("## ⚡ Last 5-minute pulse")
    x = strike_window(df, spot, cfg["step"], 25).copy()
    movers = []
    for _, r in x.iterrows():
        for side, doi_col, state_col, oi_col in [
            ("CE", "ce_doi_5m", "ce_state", "ce_oi"),
            ("PE", "pe_doi_5m", "pe_state", "pe_oi")
        ]:
            doi = float(r.get(doi_col, 0) or 0)
            if abs(doi) > 0:
                state = str(r.get(state_col, ""))
                if doi > 0:
                    action = "OI building"
                else:
                    action = "OI reducing"
                movers.append((abs(doi), side, int(r.strike), doi, state, action))
    top_pulse = sorted(movers, reverse=True)[:6]
    if top_pulse:
        pulse_cols=st.columns(3)
        for i,(mag,side,strike,doi,state,action) in enumerate(top_pulse):
            col=pulse_cols[i%3]
            icon="🟢" if side=="PE" and doi>0 else "🔴" if side=="CE" and doi>0 else "⚪"
            with col:
                st.markdown(f"""
                <div class="pulse-card">
                  <div class="pulse-top">{icon} {side} <b>{strike:,}</b></div>
                  <div class="pulse-main">{action}</div>
                  <div class="pulse-sub">ΔOI {doi:+,.0f} · {state or "no state"}</div>
                </div>
                """,unsafe_allow_html=True)
    else:
        st.info("No meaningful 5-minute OI shift captured yet.")

    # -----------------------------
    # OI BATTLEFIELD
    # -----------------------------
    st.markdown("## ⚔️ OI Battlefield")
    st.caption("Only the nearest strikes are shown here. The goal is to see where pressure is building, not to make you read the whole chain.")
    trader_oi_battlefield(df, spot, cfg["step"], levels)

    # -----------------------------
    # LEVEL HEALTH
    # -----------------------------
    st.markdown("## 🛡️ Level health")
    lh1, lh2, lh3 = st.columns(3)
    for col, label, key, side in [
        (lh1, "EOR resistance", "EOR", "resistance"),
        (lh2, "EOS support", "EOS", "support")
    ]:
        z = ctx.get(key, {})
        with col:
            st.markdown(f"### {label}")
            st.metric("Strength", f"{float(z.get('strength', levels.get('resistance_score' if side=='resistance' else 'support_score',0))):.0f}/100")
            st.caption(f"{z.get('state','ACTIVE')} • ΔOI {sign_text(z.get('shift',0))}")
    with lh3:
        st.markdown("### OI migration")
        st.write(migration_text(df, spot, cfg["step"]))

    # -----------------------------
    # PRICE / VOLATILITY SNAPSHOT
    # -----------------------------
    st.markdown("## 📍 Price & volatility")
    p1,p2,p3,p4,p5,p6 = st.columns(6)
    p1.metric("5m", f"{market.get('ret5',0):+.2f}%")
    p2.metric("15m", f"{market.get('ret15',0):+.2f}%")
    p3.metric("VWAP", f"{vwap:,.0f}" if vwap else "—", f"{spot-vwap:+.0f}" if vwap else None)
    p4.metric("India VIX", f"{vix:.2f}" if vix else "—", f"{vix_move:+.2f}%" if vix else None)
    p5.metric("ATM straddle", f"₹{expected:,.0f}" if expected else "—")
    p6.metric("ATM IV", f"{structure.get('atm_iv',0)*100:.1f}%" if np.isfinite(structure.get('atm_iv',np.nan)) else "—")
    if expected:
        st.caption(f"Options-implied movement proxy: **{spot-expected:,.0f} – {spot+expected:,.0f}**. This is a movement proxy, not a guaranteed forecast.")

    # -----------------------------
    # NARROW, HIGH-VALUE RAW DATA
    # -----------------------------
    with st.expander("📊 Quant Details — raw chain, Greeks, official data & diagnostics"):
        q1,q2,q3 = st.columns(3)
        q1.metric("PCR", f"{pcr:.2f}" if np.isfinite(pcr) else "—")
        q2.metric("Max pain", f"{structure.get('max_pain',np.nan):,.0f}" if np.isfinite(structure.get('max_pain',np.nan)) else "—")
        q3.metric("25Δ IV skew", f"{structure.get('iv_skew_25d',np.nan):+.2f}" if np.isfinite(structure.get('iv_skew_25d',np.nan)) else "—")

        st.markdown("### Futures")
        if futures.get("available"):
            st.write(f"**LTP:** {futures.get('ltp',0):,.2f} • **Basis:** {futures.get('basis',0):+.2f} ({futures.get('basis_pct',0):+.3f}%) • **OI:** {format_oi(futures.get('oi',0))} • **ΔOI:** {sign_text(futures.get('doi',0))}")
        else:
            st.info(futures.get("reason","Futures unavailable"))

        st.markdown("### Official Upstox cross-check")
        oi_info = official.get("change_oi", {})
        mp_info = official.get("max_pain", {})
        pcr_info = official.get("pcr", {})
        st.write(
            f"Call ΔOI: **{format_oi(oi_info.get('total_call_change_oi',0))}** • "
            f"Put ΔOI: **{format_oi(oi_info.get('total_put_change_oi',0))}** • "
            f"Max pain: **{num(mp_info.get('max_pain'),0):,.0f}** • "
            f"PCR: **{num(pcr_info.get('pcr'),np.nan):.2f}**"
            if pcr_info else "Official market-information data unavailable."
        )

        st.markdown("### Volume profile / previous-day structure")
        if vp:
            st.write(f"POC **{vp['poc']:,.0f}** • VAH **{vp['vah']:,.0f}** • VAL **{vp['val']:,.0f}")
        if prev:
            st.write(f"Previous high **{prev.get('prev_high',0):,.0f}** • Previous low **{prev.get('prev_low',0):,.0f}** • Previous close **{prev.get('prev_close',0):,.0f}")

        st.markdown("### Full option chain")
        option_chain_display(df, spot, cfg["step"])
        option_chain_download(df, name, expiry)

        st.markdown("### Raw OI pulse")
        ce, pe = st.columns(2)
        with ce:
            z = x.reindex(x.ce_doi_5m.abs().sort_values(ascending=False).index).head(8)
            st.dataframe(pd.DataFrame({
                "Strike": z.strike.astype(int), "CE ΔOI 5m": z.ce_doi_5m.round(0),
                "CE ΔOI day": z.ce_doi_day.round(0), "CE OI":[format_oi(v) for v in z.ce_oi],
                "Premium %": z.ce_prem_pct.round(2), "State": z.ce_state
            }), use_container_width=True, hide_index=True)
        with pe:
            z = x.reindex(x.pe_doi_5m.abs().sort_values(ascending=False).index).head(8)
            st.dataframe(pd.DataFrame({
                "Strike": z.strike.astype(int), "PE ΔOI 5m": z.pe_doi_5m.round(0),
                "PE ΔOI day": z.pe_doi_day.round(0), "PE OI":[format_oi(v) for v in z.pe_oi],
                "Premium %": z.pe_prem_pct.round(2), "State": z.pe_state
            }), use_container_width=True, hide_index=True)

        st.markdown("### Regime / confluence diagnostics")
        st.write(f"Regime: **{regime.get('regime','—')}** • Score **{regime.get('score',0):+d}**")
        st.write("Regime evidence: " + " • ".join(regime.get("labels", [])))
        st.write("EOS: " + " • ".join(confluence.get("EOS", {}).get("reasons", [])))
        st.write("EOR: " + " • ".join(confluence.get("EOR", {}).get("reasons", [])))
        st.caption(f"Primary model: {scenario['primary']} {scenario['score']:+.0f} • Exploratory all-feature model: {exploratory['primary']} {exploratory['score']:+.0f}")

    # -----------------------------
    # INDEX DRIVERS: high-value, always visible
    # -----------------------------
    with st.expander(f"🚦 What is moving {name} — open for index-impact ranking", expanded=True):
        render_contributors(token, name)

    # -----------------------------
    # MOVERS + RESEARCH

    # -----------------------------
    with st.expander("📰 Market story"):
        story = []
        story.append("The market is " + ("above" if vwap and spot > vwap else "below" if vwap else "not clearly positioned around") + " VWAP.")
        story.append("The current primary scenario is " + primary + ".")
        if dpe > dce:
            story.append("Put OI is building faster than call OI in the core chain.")
        elif dce > dpe:
            story.append("Call OI is building faster than put OI in the core chain.")
        if events.get("failed_breakout") not in (None, "", "NONE"):
            story.append("A failed-breakout condition is active, so directional confidence is reduced.")
        for line in story:
            st.write("• " + line)

    # -----------------------------
    # RISK MAP
    # -----------------------------
    with st.expander("🎯 Risk map / execution math"):
        if primary == "UPSIDE":
            trigger, stop, target = levels["eor"], levels["eor"]-cfg["step"]*0.5, levels["eor1"]
        elif primary == "DOWNSIDE":
            trigger, stop, target = levels["eos"], levels["eos"]+cfg["step"]*0.5, levels["eos1"]
        else:
            trigger, stop, target = levels["eor"], None, levels["eor1"]
        if stop is not None:
            risk_pts = abs(trigger-stop)
            reward_pts = abs(target-trigger)
            rr = reward_pts/risk_pts if risk_pts else 0
            r1,r2,r3,r4 = st.columns(4)
            r1.metric("Trigger", f"{trigger:,.0f}")
            r2.metric("Invalidation", f"{stop:,.0f}")
            r3.metric("Target", f"{target:,.0f}")
            r4.metric("Underlying R/R", f"{rr:.2f}:1")
        else:
            st.info("Wait for a confirmed move outside the EOS/EOR band before using a directional risk map.")

    # -----------------------------
    # SIGNAL VALIDATION
    # -----------------------------
    if st.button(f"Log current {name} signal", key=f"log_v4_ui_{name}"):
        j = st.session_state.setdefault("signal_journal", [])
        j.append({
            "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
            "index": name, "spot": spot, "eos": levels["eos"], "eor": levels["eor"],
            "model": scenario["score"], "primary": scenario["primary"],
            "up_scenario": scenario["up"], "range_scenario": scenario["range"],
            "down_scenario": scenario["down"], "quality": quality,
            "pcr": pcr, "max_pain": structure.get("max_pain",np.nan),
            "vwap": vwap, "vix": vix, "expiry": expiry
        })
    st.caption("Scenario weights are model outputs, not historical win probabilities. Use the Validation / Feature Lab tabs to judge out-of-sample performance.")

def render_cross_index(token):
    """Render the cross-index comparison without shadowing numeric values with Streamlit columns."""
    try:
        nifty_ltp, nifty_cp = underlying_ltp(token, INDEXES["NIFTY 50"]["key"])
        bank_ltp, bank_cp = underlying_ltp(token, INDEXES["BANK NIFTY"]["key"])
    except Exception as exc:
        st.warning(f"Cross-index data unavailable right now: {exc}")
        return

    nifty_move = (nifty_ltp / nifty_cp - 1) * 100 if nifty_cp else 0.0
    bank_move = (bank_ltp / bank_cp - 1) * 100 if bank_cp else 0.0
    relative_move = bank_move - nifty_move

    st.markdown("## ⚔️ NIFTY vs BANK NIFTY")
    col_nifty, col_bank, col_relative = st.columns(3)
    col_nifty.metric("NIFTY", f"{nifty_ltp:,.2f}", f"{nifty_move:+.2f}%")
    col_bank.metric("BANK NIFTY", f"{bank_ltp:,.2f}", f"{bank_move:+.2f}%")
    col_relative.metric("Relative", f"{relative_move:+.2f}%")

    if relative_move > 0.20:
        st.success("🟢 BANK NIFTY leadership: banking strength is exceeding the Nifty move.")
    elif relative_move < -0.20:
        st.error("🔴 BANK NIFTY lagging: banking weakness is dragging relative strength.")
    else:
        st.info("🟡 Nifty and Bank Nifty are broadly aligned.")

    render_smartlist_radar(token)


def validation_panel():
    st.markdown("## 🧪 Backtest / Validation")
    render_auto_backtest()
    st.caption("Evidence hierarchy: OOS hit rate → false-break rate → MFE/MAE → expectancy after costs → drawdown → stability by regime/expiry. Nothing here is presented as a guaranteed win rate.")
    uploaded=st.file_uploader("Upload historical signal/outcome CSV",type=["csv"],key="backtest_upload")
    if uploaded is not None:
        try:
            d=pd.read_csv(uploaded)
            st.dataframe(d.head(100),use_container_width=True,hide_index=True)
            if "model" in d.columns and "future_return" in d.columns:
                d=d.copy(); d["win"]=(d["model"]*d["future_return"]>0).astype(int)
                hit=float(d.win.mean()); mean_ret=float(d.future_return.mean())
                cost=float(d["cost_pct"].mean()) if "cost_pct" in d.columns else 0.0
                net=d.future_return-cost
                gross_pf=float(d.loc[net>0,"future_return"].sum()/abs(d.loc[net<0,"future_return"].sum())) if (net<0).any() else np.inf
                eq=net.cumsum(); dd=float((eq-eq.cummax()).min()) if len(eq) else 0
                c1,c2,c3,c4,c5=st.columns(5)
                c1.metric("Directional hit",f"{hit*100:.1f}%")
                c2.metric("Mean return",f"{mean_ret:+.3f}%")
                c3.metric("Mean cost",f"{cost:.3f}%")
                c4.metric("Profit factor",f"{gross_pf:.2f}" if np.isfinite(gross_pf) else "∞")
                c5.metric("Max drawdown",f"{dd:+.3f}%")
                if "mfe" in d.columns: st.metric("Mean MFE",f"{d.mfe.mean():+.3f}")
                if "mae" in d.columns: st.metric("Mean MAE",f"{d.mae.mean():+.3f}")
                if "false_break" in d.columns: st.metric("False-break rate",f"{d.false_break.astype(float).mean()*100:.1f}%")
                if "regime" in d.columns:
                    st.markdown("### Performance by regime")
                    g=d.groupby("regime").agg(rows=("win","size"),hit_rate=("win","mean"),mean_return=("future_return","mean")).reset_index()
                    st.dataframe(g.style.format({"hit_rate":"{:.1%}","mean_return":"{:+.3f}%"}),use_container_width=True,hide_index=True)
                if "expiry_day" in d.columns:
                    st.markdown("### Expiry-day vs normal-day")
                    g=d.groupby("expiry_day").agg(rows=("win","size"),hit_rate=("win","mean"),mean_return=("future_return","mean")).reset_index()
                    st.dataframe(g.style.format({"hit_rate":"{:.1%}","mean_return":"{:+.3f}%"}),use_container_width=True,hide_index=True)
                st.warning("Backtest results are only meaningful if the file is time-ordered, avoids look-ahead, uses realistic entry/exit timing and includes costs/slippage.")
            else:
                st.info("For full validation add at least: model, future_return. Optional: mfe, mae, false_break, cost_pct, regime, expiry_day.")
        except Exception as e:
            st.error(f"Could not read validation CSV: {e}")
    j=st.session_state.get("signal_journal",[])
    if j:
        jd=pd.DataFrame(j); st.dataframe(jd,use_container_width=True,hide_index=True)
        st.download_button("Download session signal journal",jd.to_csv(index=False).encode(),"oi_pulse_signal_journal.csv","text/csv")
    else:
        st.info("No signals logged yet. Log live signals during market hours, then attach future outcomes later for honest performance measurement.")



def inject_trader_css():
    st.markdown("""
    <style>
    .block-container{max-width:1500px;padding-top:1rem;padding-bottom:3rem}
    .stApp{background:#f5f7fb}
    .trader-shell{background:#fff;border:1px solid #e5e9f0;border-radius:18px;padding:18px 20px;box-shadow:0 8px 30px rgba(15,23,42,.05);margin-bottom:14px}
    .decision{display:grid;grid-template-columns:1.2fr .8fr .8fr .8fr;gap:10px}
    .decision .box{border:1px solid #e8ecf2;border-radius:14px;padding:12px 14px;background:#fbfcfe}
    .decision .label{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;font-weight:800}
    .decision .big{font-size:25px;font-weight:850;line-height:1.15;color:#172033}
    .decision .sub{font-size:11px;color:#64748b;margin-top:4px}
    .bull{border-left:4px solid #16a36a!important}.bear{border-left:4px solid #e5484d!important}.range{border-left:4px solid #d98b18!important}
    .mini-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
    .mini{background:#fff;border:1px solid #e7ebf0;border-radius:12px;padding:9px 11px}
    .mini .k{font-size:10px;color:#64748b;text-transform:uppercase;font-weight:800}
    .mini .v{font-size:15px;font-weight:800;color:#172033}
    .section-title{display:flex;align-items:baseline;justify-content:space-between;margin:18px 0 8px}
    .section-title h3{margin:0;font-size:18px}.section-title span{font-size:11px;color:#64748b}
    .reason-card{background:#fff;border:1px solid #e7ebf0;border-radius:14px;padding:12px 14px}
    .reason{padding:7px 0;border-bottom:1px solid #f0f2f5;font-size:13px}.reason:last-child{border-bottom:0}
    .pulse-card{height:92px;background:#fff;border:1px solid #e7ebf0;border-radius:14px;padding:12px;box-shadow:0 3px 14px rgba(15,23,42,.035)}
    .pulse-top{font-size:12px;color:#475569}.pulse-main{font-size:15px;font-weight:800;margin-top:6px}.pulse-sub{font-size:11px;color:#64748b;margin-top:3px}
    .level-stack{display:flex;flex-direction:column;gap:5px}
    .level-stack .lvl{display:grid;grid-template-columns:70px 1fr 1fr;align-items:center;padding:9px 12px;border-radius:10px}
    .level-stack .lvl b{font-size:18px;text-align:center}.level-stack small{text-align:right;color:#64748b}
    .redlvl{background:#fff1f2;color:#9f1239}.greenlvl{background:#ecfdf5;color:#047857}.spotlvl{background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe}
    .ext{opacity:.72}
    @media(max-width:900px){.decision{grid-template-columns:1fr 1fr}.mini-grid{grid-template-columns:repeat(3,1fr)}}
    </style>
    """, unsafe_allow_html=True)

def main():
    inject_trader_css()
    token=token_from_secrets()
    with st.sidebar:
        st.header("⚡ OI Pulse Pro")
        if not token: token=st.text_input("Upstox access token",type="password")
        refresh=st.slider("Refresh (seconds)",3,15,5)
        st.checkbox("Use V3 WebSocket when available",value=True,key="use_ws")
        st.checkbox("Evidence-first live model (recommended)",value=True,key="evidence_first")
        st.text_input("Optional event-risk note",value="",key="event_risk_note",placeholder="e.g. RBI / CPI / major expiry event")
        st.number_input("Max underlying risk budget (₹)",min_value=0.0,value=5000.0,step=500.0,key="risk_budget")
        uploaded=st.file_uploader("Optional current index weights CSV",type=["csv"])
        if uploaded is not None: st.session_state["uploaded_weights"]=uploaded
        st.caption("CSV columns: symbol,weight_pct. This replaces the dated reference weights for the stock-flow section.")
        st.caption(f"Last refresh: {datetime.now(IST).strftime('%H:%M:%S IST')}")
        st.caption("Evidence policy: experimental features are visible immediately, but only OOS-positive features are allowed to influence the primary live scenario when Evidence-first is enabled.")
    if not token:
        st.info("Add UPSTOX_ACCESS_TOKEN to Streamlit Secrets."); return
    st.title("⚡ OI Pulse Pro")
    st.caption("Trader-first NIFTY & BANK NIFTY terminal • OI battlefield • levels • futures • regime • index drivers • research")
    @st.fragment(run_every=f"{refresh}s")
    def live():
        render_cross_index(token)
        tabs=st.tabs(["NIFTY 50","BANK NIFTY","SIGNAL VALIDATION","FEATURE LAB"])
        with tabs[0]:
            render_index_v3("NIFTY 50",token)
        with tabs[1]:
            render_index_v3("BANK NIFTY",token)
        with tabs[2]: validation_panel()
        with tabs[3]: feature_gate_panel()
    live()

if __name__=="__main__": main()
