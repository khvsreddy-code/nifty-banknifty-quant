import math
import threading
import time
import json
import gzip
import io
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from urllib.parse import quote
import streamlit as st
try:
    from streamlit_searchbox import st_searchbox
except Exception:
    st_searchbox = None
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

# ---------------- SUPABASE PERSISTENCE ----------------
# The live terminal can run without Supabase. When credentials are present in
# Streamlit Secrets, one-minute research snapshots are persisted externally.
SUPABASE_TIMEOUT = 12

def _supabase_config():
    try:
        url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
        key = str(st.secrets.get("SUPABASE_KEY", "")).strip()
    except Exception:
        return "", ""
    return url, key

def _supabase_headers():
    url, key = _supabase_config()
    if not url or not key:
        return None
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

def supabase_enabled():
    url, key = _supabase_config()
    return bool(url and key)

def _json_number(v):
    try:
        x = float(v)
        return x if np.isfinite(x) else None
    except Exception:
        return None

def _post_supabase(table, rows, on_conflict=None):
    if not rows:
        return True, 0
    url, _ = _supabase_config()
    headers = _supabase_headers()
    if not url or not headers:
        return False, 0
    endpoint = f"{url}/rest/v1/{table}"
    params = {}
    if on_conflict:
        params["on_conflict"] = on_conflict
    try:
        r = requests.post(endpoint, params=params, headers=headers, json=rows,
                           timeout=SUPABASE_TIMEOUT)
        if r.status_code in (200, 201, 204):
            return True, len(rows)
        return False, 0
    except Exception:
        return False, 0

def _supabase_minute(now=None):
    now = now or datetime.now(IST)
    return now.replace(second=0, microsecond=0)

def save_supabase_minute(name, spot, expiry, df, levels, scenario, market,
                         structure, futures, regime, events):
    """Persist one complete research snapshot per index/minute.
    Raw option-chain rows and the model state are stored separately so the
    level engine can be re-tested later without hindsight.
    """
    if not supabase_enabled():
        return {"enabled": False, "saved": False, "rows": 0}

    now = _supabase_minute()
    today = now.date().isoformat()
    ts = now.isoformat()

    # Never write outside the normal NSE cash session.
    if now.weekday() >= 5 or now.hour < 9 or (now.hour == 9 and now.minute < 15) or now.hour > 15 or (now.hour == 15 and now.minute > 30):
        return {"enabled": True, "saved": False, "rows": 0, "reason": "outside_session"}

    # Streamlit can rerun/fragment-refresh several times inside one minute.
    # Session-state prevents repeated writes during the same process.
    dedupe_key = f"{name}|{ts}"
    done = st.session_state.setdefault("_supabase_minutes", set())
    if dedupe_key in done:
        return {"enabled": True, "saved": False, "rows": 0, "reason": "duplicate"}

    # Market snapshot.
    mrow = {
        "captured_at": ts,
        "capture_minute": ts,
        "trading_date": today,
        "index_name": name,
        "spot": _json_number(spot),
        "open_price": _json_number(market.get("open")),
        "high_price": _json_number(market.get("high")),
        "low_price": _json_number(market.get("low")),
        "volume": _json_number(market.get("volume")),
        "vwap": _json_number(market.get("vwap")),
        "day_change": _json_number(market.get("change", market.get("day_change"))),
        "day_change_pct": _json_number(market.get("change_pct", market.get("day_change_pct"))),
        "futures_price": _json_number(futures.get("price")),
        "futures_oi": _json_number(futures.get("oi")),
        "futures_change_oi": _json_number(futures.get("change_oi", futures.get("doi"))),
        "futures_volume": _json_number(futures.get("volume")),
        "futures_vwap": _json_number(futures.get("vwap")),
        "futures_basis_pct": _json_number(futures.get("basis_pct")),
        "basis": _json_number(futures.get("basis")),
        "pcr": _json_number(structure.get("pcr")),
        "regime": str(regime.get("regime","")),
        "bias": str(scenario.get("primary","")),
        "confluence_score": _json_number(scenario.get("score")),
    }

    okm, _ = _post_supabase(
        "market_snapshots", [mrow],
        "index_name,capture_minute"
    )

    # Complete option chain for this minute. Keep raw-ish fields rather than
    # only the strongest OI strikes so future research can recompute levels.
    option_rows = []
    for _, r in df.iterrows():
        # Preserve every common quote field exposed by the option-chain
        # normalizer when present. Missing fields remain NULL.
        option_rows.append({
            "captured_at": ts,
            "capture_minute": ts,
            "trading_date": today,
            "index_name": name,
            "expiry": str(expiry) if expiry else None,
            "spot": _json_number(spot),
            "strike": _json_number(r.get("strike")),

            "ce_ltp": _json_number(r.get("ce_ltp")),
            "ce_ltp_change": _json_number(r.get("ce_ltp_change", r.get("ce_change"))),
            "ce_oi": _json_number(r.get("ce_oi")),
            "ce_change_oi": _json_number(r.get("ce_doi", r.get("ce_change_oi"))),
            "ce_volume": _json_number(r.get("ce_vol", r.get("ce_volume"))),
            "ce_bid": _json_number(r.get("ce_bid", r.get("ce_bid_price"))),
            "ce_ask": _json_number(r.get("ce_ask", r.get("ce_ask_price"))),
            "ce_bid_qty": _json_number(r.get("ce_bid_qty", r.get("ce_bid_quantity"))),
            "ce_ask_qty": _json_number(r.get("ce_ask_qty", r.get("ce_ask_quantity"))),
            "ce_iv": _json_number(r.get("ce_iv")),
            "ce_delta": _json_number(r.get("ce_delta")),
            "ce_gamma": _json_number(r.get("ce_gamma")),
            "ce_theta": _json_number(r.get("ce_theta")),
            "ce_vega": _json_number(r.get("ce_vega")),

            "pe_ltp": _json_number(r.get("pe_ltp")),
            "pe_ltp_change": _json_number(r.get("pe_ltp_change", r.get("pe_change"))),
            "pe_oi": _json_number(r.get("pe_oi")),
            "pe_change_oi": _json_number(r.get("pe_doi", r.get("pe_change_oi"))),
            "pe_volume": _json_number(r.get("pe_vol", r.get("pe_volume"))),
            "pe_bid": _json_number(r.get("pe_bid", r.get("pe_bid_price"))),
            "pe_ask": _json_number(r.get("pe_ask", r.get("pe_ask_price"))),
            "pe_bid_qty": _json_number(r.get("pe_bid_qty", r.get("pe_bid_quantity"))),
            "pe_ask_qty": _json_number(r.get("pe_ask_qty", r.get("pe_ask_quantity"))),
            "pe_iv": _json_number(r.get("pe_iv")),
            "pe_delta": _json_number(r.get("pe_delta")),
            "pe_gamma": _json_number(r.get("pe_gamma")),
            "pe_theta": _json_number(r.get("pe_theta")),
            "pe_vega": _json_number(r.get("pe_vega")),
        })
    oko, nopt = _post_supabase(
        "option_chain_snapshots", option_rows,
        "index_name,capture_minute,expiry,strike"
    )

    # Store the exact level state used by the UI/chart.
    lrow = {
        "captured_at": ts,
        "capture_minute": ts,
        "trading_date": today,
        "index_name": name,
        "spot": _json_number(spot),
        "support": _json_number(levels.get("support")),
        "support_precision": _json_number(levels.get("support_precision")),
        "resistance": _json_number(levels.get("resistance")),
        "resistance_precision": _json_number(levels.get("resistance_precision")),
        "support_oi": _json_number(levels.get("support_oi")),
        "resistance_oi": _json_number(levels.get("resistance_oi")),
        "support_strength": _json_number(levels.get("support_strength")),
        "resistance_strength": _json_number(levels.get("resistance_strength")),
        "support_state": str(levels.get("support_state","ACTIVE")),
        "resistance_state": str(levels.get("resistance_state","ACTIVE")),
        "eos": _json_number(levels.get("eos")),
        "eor": _json_number(levels.get("eor")),
        "regime": str(regime.get("regime","")),
        "bias": str(scenario.get("primary","")),
    }
    okl, _ = _post_supabase(
        "level_snapshots", [lrow],
        "index_name,capture_minute"
    )

    # Save the prediction separately from its later outcome.
    prow = {
        "captured_at": ts,
        "capture_minute": ts,
        "trading_date": today,
        "index_name": name,
        "spot": _json_number(spot),
        "direction": str(scenario.get("primary","")),
        "confidence": _json_number(scenario.get("score")),
        "target_1": _json_number(levels.get("eor1") if scenario.get("primary") == "UPSIDE" else levels.get("eos1")),
        "target_2": _json_number(levels.get("eor2") if scenario.get("primary") == "UPSIDE" else levels.get("eos2")),
        "stop_level": _json_number(levels.get("eos") if scenario.get("primary") == "UPSIDE" else levels.get("eor")),
        "support": _json_number(levels.get("support")),
        "resistance": _json_number(levels.get("resistance")),
        "regime": str(regime.get("regime","")),
        "reasoning": {
            "score": _json_number(scenario.get("score")),
            "up": _json_number(scenario.get("up")),
            "range": _json_number(scenario.get("range")),
            "down": _json_number(scenario.get("down")),
            "failed_breakout": str(events.get("failed_breakout","NONE")),
        },
    }
    okp, _ = _post_supabase(
        "prediction_snapshots", [prow],
        "index_name,capture_minute"
    )

    if okm or oko or okl or okp:
        done.add(dedupe_key)
        # Bound memory.
        if len(done) > 5000:
            st.session_state["_supabase_minutes"] = set(list(done)[-2500:])

    return {
        "enabled": True,
        "saved": bool(okm and oko and okl and okp),
        "rows": nopt,
        "timestamp": ts,
        "market": okm,
        "options": oko,
        "levels": okl,
        "predictions": okp,
    }

def render_supabase_status():
    if not supabase_enabled():
        st.caption("Database: not configured — live dashboard still works.")
        return
    status = st.session_state.get("_supabase_last_status")
    if status and status.get("saved"):
        st.caption(f"🟢 Database recording • last saved {status.get('timestamp','')[-8:]} • option rows {status.get('rows',0)}")
    elif status:
        st.caption("🟡 Database configured • waiting for the next one-minute save")
    else:
        st.caption("🟢 Database configured • recording begins during market hours")

INDEXES = {
    "NIFTY 50": {"key": "NSE_INDEX|Nifty 50", "step": 50, "strike_window": 14, "exchange": "NSE", "trading_symbol": "NIFTY"},
    "BANK NIFTY": {"key": "NSE_INDEX|Nifty Bank", "step": 100, "strike_window": 14, "exchange": "NSE", "trading_symbol": "BANKNIFTY"},
}

# Upstox publishes the BOD instrument universe as JSON/GZIP.  We use that public
# universe to populate the index selector instead of maintaining a brittle hard-coded list.
# NIFTY/BANK NIFTY remain as a guaranteed fallback if the public file is temporarily unavailable.
INDEX_FILE_URLS = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz",
)

@st.cache_data(ttl=21600, show_spinner=False)

# ---------------- Level lifecycle engine ----------------

# ---------------- Live chart level integration ----------------

@st.cache_data(ttl=4, show_spinner=False)
def upstox_intraday_candles_df(token, key, minutes=5):
    """Fetch selected-timeframe Upstox candles; on non-trading days fall back to latest session."""
    import datetime as _dt

    empty = pd.DataFrame(columns=["time","open","high","low","close","volume"])

    def parse(data):
        candles = ((data.get("data") or {}).get("candles") or []) if isinstance(data, dict) else []
        rows=[]
        for c in candles:
            if len(c) < 5:
                continue
            ts=c[0]
            try:
                if isinstance(ts, str):
                    dt=_dt.datetime.fromisoformat(ts.replace("Z","+00:00"))
                    epoch=int(dt.timestamp())
                else:
                    epoch=int(float(ts))
                    if epoch > 10**12:
                        epoch//=1000
            except Exception:
                continue
            o,h,l,cl=[num(v) for v in c[1:5]]
            if None in (o,h,l,cl):
                continue
            vol=num(c[5]) if len(c)>5 else 0
            rows.append({"time":epoch,"open":float(o),"high":float(h),
                         "low":float(l),"close":float(cl),"volume":float(vol or 0)})
        if not rows:
            return empty.copy()
        return pd.DataFrame(rows).drop_duplicates("time").sort_values("time").tail(500)

    try:
        d = api_get3(
            f"/historical-candle/intraday/{quote(key, safe='')}/minutes/{int(minutes)}",
            token
        )
        df=parse(d)
        if not df.empty:
            df.attrs["chart_status"]="LIVE • CURRENT SESSION"
            return df
    except Exception:
        pass

    today=_dt.date.today()
    for back in range(1,8):
        day=today-_dt.timedelta(days=back)
        ds=day.isoformat()
        try:
            d=api_get3(
                f"/historical-candle/{quote(key, safe='')}/minutes/{int(minutes)}/{ds}/{ds}",
                token
            )
            df=parse(d)
            if not df.empty:
                df.attrs["chart_status"]="LAST SESSION • MARKET CLOSED"
                df.attrs["session_date"]=ds
                return df
        except Exception:
            continue

    return empty



def supabase_live_config_for_browser():
    url, key = _supabase_config()
    return url, key

def render_upstox_tv_chart(candles, spot, levels, name, tf_minutes=5, token='', live_symbol=''):
    """Professional TradingView-inspired Lightweight Charts workspace."""
    import streamlit.components.v1 as components
    import json as _json
    if candles is None or getattr(candles, "empty", True):
        st.warning(f"{name}: no Upstox candle history is available for the chart yet.")
        return
    status=candles.attrs.get("chart_status", "UPSTOX CANDLES")
    session_date=candles.attrs.get("session_date", "")
    if status.startswith("LAST SESSION"):
        st.info(f"🕒 Market closed / non-trading day — showing the latest completed session ({session_date}).")
    rows=[]
    for _,r in candles.iterrows():
        try:
            rows.append({"time":int(r["time"]),"open":float(r["open"]),"high":float(r["high"]),"low":float(r["low"]),"close":float(r["close"]),"volume":float(r.get("volume",0) or 0)})
        except Exception:
            pass
    life=_level_lifecycle_engine(levels, spot)
    line_levels=[]; seen=set()
    for side in ("support","resistance"):
        for x in life.get(side,[])[:4]:
            if x.get("state")=="BROKEN": continue
            price=float(x["precision"]); structural=float(x["structural"])
            key=(side,round(price,2),round(structural,2))
            if key in seen: continue
            seen.add(key)
            line_levels.append({"price":price,"structural":structural,"side":side,"state":x.get("state","ACTIVE"),"tests":int(x.get("tests",0))})
    payload=_json.dumps(rows); lvl=_json.dumps(line_levels); nm=_json.dumps(str(name)); tf=_json.dumps(int(tf_minutes)); sb_url, sb_key = supabase_live_config_for_browser(); sb_url_json=_json.dumps(sb_url); sb_key_json=_json.dumps(sb_key); live_symbol_json=_json.dumps(str(live_symbol or name))
    html = '''<!doctype html><html><head><meta charset="utf-8">
<script src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
*{box-sizing:border-box}html,body{margin:0;padding:0;background:#fff;font-family:Inter,system-ui,-apple-system,Segoe UI,Arial;color:#0f172a;overflow:hidden}
#wrap{height:760px;position:relative;border:1px solid #d9e1ea;border-radius:12px;overflow:hidden;background:#fff;box-shadow:0 8px 28px rgba(15,23,42,.08)}
#top{height:48px;display:flex;align-items:center;gap:7px;padding:7px 10px;border-bottom:1px solid #e5eaf0;background:#fff}
.symbol{font-weight:750;font-size:14px;color:#172033;padding:0 7px}.live{font-size:9px;color:#087443;border:1px solid #b8e4cf;background:#ecfdf3;border-radius:20px;padding:3px 7px}
button,select{border:1px solid #d5dde7;background:#fff;color:#334155;border-radius:7px;padding:6px 9px;font-size:11px;cursor:pointer;outline:none}button:hover,button.on{background:#eef5ff;border-color:#7aa2cc;color:#0f172a}button.danger{color:#fda4af}button.primary{background:#eef6ff;border-color:#8ab1d8;color:#174a7e}.spacer{flex:1}
#toolbar{height:42px;display:flex;align-items:center;gap:5px;padding:5px 9px;border-bottom:1px solid #e5eaf0;background:#fff;overflow-x:auto;white-space:nowrap}.group{display:flex;gap:4px;align-items:center}.label{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:#72849a;margin:0 3px}.sep{width:1px;height:23px;background:#e2e8f0;margin:0 4px}
#workspace{position:relative;height:670px}.left{position:absolute;z-index:30;left:7px;top:8px;width:34px;background:#fff;border:1px solid #d5dde7;border-radius:9px;display:flex;flex-direction:column;gap:3px;padding:4px}.left button{width:26px;height:26px;padding:0;font-size:14px}.left button.on{background:#214361;color:#fff}
#main{position:absolute;left:48px;right:0;top:0;height:480px}.pane{position:absolute;left:48px;right:0;top:480px;height:90px;border-top:1px solid #e5eaf0}.volpane{position:absolute;left:48px;right:0;top:570px;height:90px;border-top:1px solid #e5eaf0}.pane-title{position:absolute;left:8px;top:5px;z-index:4;font-size:9px;color:#64748b;background:#ffffffdd;padding:2px 5px;border-radius:4px}
#float{position:absolute;z-index:40;right:10px;top:8px;display:flex;gap:5px}.badge{font-size:9px;padding:5px 7px;border-radius:6px;background:#fff;border:1px solid #d5dde7;color:#64748b}.badge strong{color:#334155}.hint{position:absolute;z-index:40;left:55px;bottom:7px;font-size:9px;color:#64748b;pointer-events:none}
 .modal{position:absolute;z-index:60;right:9px;top:52px;width:300px;background:#fff;border:1px solid #d5dde7;border-radius:10px;box-shadow:0 18px 50px rgba(15,23,42,.16);padding:10px;display:none}.modal h4{margin:0 0 8px;font-size:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}.small{font-size:9px;color:#8193a8;margin:7px 0 4px}
</style></head><body><div id="wrap">
<div id="top"><div class="symbol">__NAME__</div><span class="live">● UPSTOX</span><span class="badge">OI levels <strong>LIVE</strong></span><div class="spacer"></div><button onclick="fit()">Fit</button><button onclick="toggleFullscreen()">⛶</button></div>
<div id="toolbar"><div class="group"><span class="label">Chart</span><button class="on" id="candleBtn" onclick="setType('candle')">Candles</button><button id="lineBtn" onclick="setType('line')">Line</button></div><div class="sep"></div><div class="group"><span class="label">Range</span><button onclick="range(30)">30m</button><button onclick="range(60)">1H</button><button onclick="range(180)">3H</button><button onclick="fit()">All</button></div><div class="sep"></div><div class="group"><span class="label">Indicators</span><button class="on" id="ema20" onclick="toggle('ema20')">EMA20</button><button id="ema50" onclick="toggle('ema50')">EMA50</button><button id="vwap" onclick="toggle('vwap')">VWAP</button><button id="bb" onclick="toggle('bb')">BB</button><button onclick="openIndicators()" class="primary">＋ Indicators</button></div><div class="sep"></div><button onclick="toggleLevels()" class="on" id="levelsBtn">S/R Levels</button><button onclick="openSettings()">⚙</button></div>
<div id="workspace"><div class="left">
<button title="Cursor" id="cursor" class="on" onclick="drawMode(null)">⌁</button><button title="Horizontal line" id="hline" onclick="drawMode('hline')">—</button><button title="Trendline" id="trend" onclick="drawMode('trend')">╱</button><button title="Ray" id="ray" onclick="drawMode('ray')">↗</button><button title="Zone" id="zone" onclick="drawMode('zone')">▱</button><button title="Vertical line" id="vline" onclick="drawMode('vline')">│</button><button title="Fibonacci" id="fib" onclick="drawMode('fib')">F</button><button title="Undo" onclick="undo()">↶</button><button title="Clear drawings" class="danger" onclick="clearDrawings()">⌫</button></div>
<div id="float"><span class="badge">Draw: <strong id="modeLabel">Cursor</strong></span><span class="badge">Precision levels: <strong>ON</strong></span></div>
<div id="main"></div><div class="pane"><div class="pane-title" id="paneTitle">RSI 14</div><div id="indicatorPane" style="width:100%;height:100%"></div></div><div class="volpane"><div class="pane-title">VOLUME</div><div id="volumePane" style="width:100%;height:100%"></div></div>
<div class="hint" id="hint">TradingView-style workspace • choose a drawing tool or indicator.</div>
<div class="modal" id="indicatorModal"><h4>Indicators</h4><div class="small">OVERLAYS</div><div class="grid"><button onclick="toggle('ema20')">EMA 20</button><button onclick="toggle('ema50')">EMA 50</button><button onclick="toggle('vwap')">VWAP</button><button onclick="toggle('bb')">Bollinger Bands</button><button onclick="toggle('sma20')">SMA 20</button><button onclick="toggle('sma50')">SMA 50</button></div><div class="small">OSCILLATORS / VOLATILITY</div><div class="grid"><button onclick="setPane('RSI')">RSI 14</button><button onclick="setPane('MACD')">MACD</button><button onclick="setPane('ATR')">ATR 14</button><button onclick="setPane('STOCH')">Stochastic</button><button onclick="setPane('ADX')">ADX</button><button onclick="setPane('OBV')">OBV</button></div><div class="small">TREND</div><div class="grid"><button onclick="setPane('SUPERTREND')">Supertrend</button><button onclick="setPane('NONE')">Hide pane</button></div></div>
<div class="modal" id="settingsModal"><h4>Chart settings</h4><div class="small">WORKSPACE</div><div class="grid"><button onclick="toggleGrid()">Grid</button><button onclick="toggleCrosshair()">Crosshair</button><button onclick="toggleLevels()">Auto levels</button><button onclick="fit()">Fit content</button></div></div>
</div></div>
<script>
const DATA=__DATA__, LEVELS=__LEVELS__, TF_MINUTES=__TF_MINUTES__, LIVE_SYMBOL=__LIVE_SYMBOL__, KEY='nifty_tv_drawings_'+__NAME_JSON__;
const mainEl=document.getElementById('main'), paneEl=document.getElementById('indicatorPane'), volEl=document.getElementById('volumePane');
const chart=LightweightCharts.createChart(mainEl,{autoSize:true,height:480,layout:{background:{type:'solid',color:'#ffffff'},textColor:'#334155',fontFamily:'Inter,system-ui,sans-serif',fontSize:12},grid:{vertLines:{color:'#edf1f5'},horzLines:{color:'#edf1f5'}},crosshair:{mode:LightweightCharts.CrosshairMode.Magnet,vertLine:{color:'#94a3b8',width:1,style:LightweightCharts.LineStyle.Dashed,labelBackgroundColor:'#334155'},horzLine:{color:'#94a3b8',width:1,style:LightweightCharts.LineStyle.Dashed,labelBackgroundColor:'#334155'}},rightPriceScale:{borderColor:'#d8e0e8',scaleMargins:{top:.07,bottom:.08},autoScale:true,entireTextOnly:true},timeScale:{borderColor:'#d8e0e8',timeVisible:true,secondsVisible:false,rightOffset:5,barSpacing:7,minBarSpacing:2,shiftVisibleRangeOnNewBar:true},handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true},handleScale:{axisPressedMouseMove:{time:true,price:true},mouseWheel:true,pinch:true},kineticScroll:{mouse:true,touch:true},localization:{locale:'en-IN',priceFormatter:p=>Number(p).toLocaleString('en-IN',{maximumFractionDigits:2})}});
const cs=chart.addSeries(LightweightCharts.CandlestickSeries,{upColor:'#16a34a',downColor:'#dc2626',borderUpColor:'#16a34a',borderDownColor:'#dc2626',wickUpColor:'#16a34a',wickDownColor:'#dc2626',lastValueVisible:true,priceLineVisible:true,priceLineColor:'#2563eb',priceLineWidth:1,priceLineStyle:LightweightCharts.LineStyle.Dotted});cs.setData(DATA);const ls=chart.addSeries(LightweightCharts.LineSeries,{color:'#d8e2ee',lineWidth:2,visible:false,priceLineVisible:false,lastValueVisible:false});ls.setData(DATA.map(x=>({time:x.time,value:x.close})));
const volChart=LightweightCharts.createChart(volEl,{width:volEl.clientWidth,height:90,layout:{background:{type:'solid',color:'#ffffff'},textColor:'#71849a'},grid:{vertLines:{color:'#f1f5f9'},horzLines:{color:'#f1f5f9'}},rightPriceScale:{borderColor:'#d8e0e8'},timeScale:{visible:false}});const vol=volChart.addSeries(LightweightCharts.HistogramSeries,{priceFormat:{type:'volume'},priceScaleId:'vol'});vol.priceScale().applyOptions({scaleMargins:{top:.15,bottom:.05}});vol.setData(DATA.map(x=>({time:x.time,value:x.volume,color:x.close>=x.open?'#1d7f5c99':'#9b3b4699'})));
const pane=LightweightCharts.createChart(paneEl,{width:paneEl.clientWidth,height:90,layout:{background:{type:'solid',color:'#ffffff'},textColor:'#71849a'},grid:{vertLines:{color:'#f1f5f9'},horzLines:{color:'#f1f5f9'}},rightPriceScale:{borderColor:'#d8e0e8'},timeScale:{visible:false}});let p1=pane.addSeries(LightweightCharts.LineSeries,{color:'#2563eb',lineWidth:2,priceLineVisible:false,lastValueVisible:true}),p2=pane.addSeries(LightweightCharts.LineSeries,{color:'#f59e0b',lineWidth:1,priceLineVisible:false,lastValueVisible:true});
const overlays={},state={levels:true,grid:true,crosshair:true};
function ema(n){let a=2/(n+1),p=null;return DATA.map(x=>{p=p==null?x.close:x.close*a+p*(1-a);return{time:x.time,value:p}})}function sma(n){return DATA.map((x,i)=>{let q=DATA.slice(Math.max(0,i-n+1),i+1).map(y=>y.close);return{time:x.time,value:q.reduce((a,b)=>a+b,0)/q.length}})}
function addLine(key,data,color,width=2){if(overlays[key])return;let s=chart.addSeries(LightweightCharts.LineSeries,{color,lineWidth:width,priceLineVisible:false,lastValueVisible:false});s.setData(data);overlays[key]=s}function remove(k){let s=overlays[k];if(!s)return;(Array.isArray(s)?s:[s]).forEach(x=>chart.removeSeries(x));delete overlays[k]}
function addBB(){if(overlays.bb)return;let m=[],u=[],d=[];DATA.forEach((x,i)=>{let q=DATA.slice(Math.max(0,i-19),i+1).map(y=>y.close),a=q.reduce((z,v)=>z+v,0)/q.length,sd=Math.sqrt(q.reduce((z,v)=>z+(v-a)**2,0)/q.length);m.push({time:x.time,value:a});u.push({time:x.time,value:a+2*sd});d.push({time:x.time,value:a-2*sd})});addLine('bbm',m,'#8b9aab',1);addLine('bbu',u,'#38bdf8',1);addLine('bbd',d,'#38bdf8',1);overlays.bb=true}function addVWAP(){let cp=0,cv=0;addLine('vwap',DATA.map(x=>{cp+=(x.high+x.low+x.close)/3*x.volume;cv+=x.volume;return{time:x.time,value:cv?cp/cv:x.close}}),'#c084fc',2)}
function toggle(k){let b=document.getElementById(k);if(b)b.classList.toggle('on');let on=b?b.classList.contains('on'):true;if(k==='ema20'){on?addLine('ema20',ema(20),'#60a5fa'):remove('ema20')}if(k==='ema50'){on?addLine('ema50',ema(50),'#f59e0b'):remove('ema50')}if(k==='sma20'){on?addLine('sma20',sma(20),'#94a3b8',1):remove('sma20')}if(k==='sma50'){on?addLine('sma50',sma(50),'#e879f9',1):remove('sma50')}if(k==='vwap'){on?addVWAP():remove('vwap')}if(k==='bb'){on?addBB():(remove('bbm'),remove('bbu'),remove('bbd'),delete overlays.bb)}}
function rsi(n=14){let g=[],l=[],o=[];for(let i=1;i<DATA.length;i++){let c=DATA[i].close-DATA[i-1].close;g.push(Math.max(c,0));l.push(Math.max(-c,0));if(g.length>n){g.shift();l.shift()}let ag=g.reduce((a,b)=>a+b,0)/g.length,al=l.reduce((a,b)=>a+b,0)/l.length;o.push({time:DATA[i].time,value:al?100-100/(1+ag/al):100})}return o}function macd(){let a=ema(12),b=ema(26),m=a.map((x,i)=>({time:x.time,value:x.value-b[i].value})),sig=[],p=null,k=2/10;m.forEach(x=>{p=p==null?x.value:x.value*k+p*(1-k);sig.push({time:x.time,value:p})});return[m,sig]}function atr(n=14){let tr=DATA.map((x,i)=>i?Math.max(x.high-x.low,Math.abs(x.high-DATA[i-1].close),Math.abs(x.low-DATA[i-1].close)):x.high-x.low);return DATA.map((x,i)=>({time:x.time,value:tr.slice(Math.max(0,i-n+1),i+1).reduce((a,b)=>a+b,0)/Math.min(n,i+1)}))}function stoch(n=14){return DATA.map((x,i)=>{let q=DATA.slice(Math.max(0,i-n+1),i+1),lo=Math.min(...q.map(z=>z.low)),hi=Math.max(...q.map(z=>z.high));return{time:x.time,value:hi===lo?50:(x.close-lo)/(hi-lo)*100}})}function obv(){let v=0;return DATA.map((x,i)=>{if(i)v+=x.close>DATA[i-1].close?x.volume:x.close<DATA[i-1].close?-x.volume:0;return{time:x.time,value:v}})}function adx(){let tr=[],dm=[],p=14;for(let i=1;i<DATA.length;i++){let up=DATA[i].high-DATA[i-1].high,dn=DATA[i-1].low-DATA[i].low;tr.push(Math.max(DATA[i].high-DATA[i].low,Math.abs(DATA[i].high-DATA[i-1].close),Math.abs(DATA[i].low-DATA[i-1].close)));dm.push(up>dn&&up>0?up:dn>up&&dn>0?-dn:0)}return DATA.map((x,i)=>{let T=tr.slice(Math.max(0,i-p),i+1),D=dm.slice(Math.max(0,i-p),i+1),a=T.reduce((s,z)=>s+z,0)/T.length,b=D.reduce((s,z)=>s+z,0)/D.length;return{time:x.time,value:a?Math.abs(b/a)*100:0}})}
function setPane(kind){document.getElementById('indicatorModal').style.display='none';p1.setData([]);p2.setData([]);document.getElementById('paneTitle').textContent=kind==='NONE'?'':kind==='SUPERTREND'?'SUPERTREND':kind+' 14';if(kind==='NONE')return;if(kind==='RSI')p1.setData(rsi());if(kind==='MACD'){let[a,b]=macd();p1.setData(a);p2.setData(b)}if(kind==='ATR')p1.setData(atr());if(kind==='STOCH')p1.setData(stoch());if(kind==='ADX')p1.setData(adx());if(kind==='OBV')p1.setData(obv());if(kind==='SUPERTREND')p1.setData(DATA.map(x=>({time:x.time,value:(x.high+x.low)/2})))}
function openIndicators(){document.getElementById('indicatorModal').style.display=document.getElementById('indicatorModal').style.display==='block'?'none':'block';document.getElementById('settingsModal').style.display='none'}function openSettings(){document.getElementById('settingsModal').style.display=document.getElementById('settingsModal').style.display==='block'?'none':'block';document.getElementById('indicatorModal').style.display='none'}
let levelSeries=[];LEVELS.forEach(x=>levelSeries.push(cs.createPriceLine({price:x.price,color:x.side==='support'?'#22c55e':'#ef4444',lineWidth:2,lineStyle:LightweightCharts.LineStyle.Solid,axisLabelVisible:true,title:(x.side==='support'?'S ':'R ')+x.price.toFixed(2)})));function toggleLevels(){state.levels=!state.levels;document.getElementById('levelsBtn').classList.toggle('on',state.levels);levelSeries.forEach(s=>s.applyOptions({visible:state.levels}))}function toggleGrid(){state.grid=!state.grid;chart.applyOptions({grid:{vertLines:{visible:state.grid,color:'#172334'},horzLines:{visible:state.grid,color:'#172334'}}})}function toggleCrosshair(){state.crosshair=!state.crosshair;chart.applyOptions({crosshair:{mode:state.crosshair?LightweightCharts.CrosshairMode.Normal:LightweightCharts.CrosshairMode.Hidden}})}function setType(t){cs.applyOptions({visible:t==='candle'});ls.applyOptions({visible:t==='line'});document.getElementById('candleBtn').classList.toggle('on',t==='candle');document.getElementById('lineBtn').classList.toggle('on',t==='line')}function range(mins){if(!DATA.length)return;let end=DATA[DATA.length-1].time,start=end-mins*60;chart.timeScale().setVisibleRange({from:start,to:end});volChart.timeScale().setVisibleRange({from:start,to:end});pane.timeScale().setVisibleRange({from:start,to:end})}function fit(){chart.timeScale().fitContent();volChart.timeScale().fitContent();pane.timeScale().fitContent();renderDrawings()}function toggleFullscreen(){let x=document.getElementById('wrap');if(!document.fullscreenElement)x.requestFullscreen();else document.exitFullscreen()}
let drawings=JSON.parse(localStorage.getItem(KEY)||'[]'),mode=null,pending=null;const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.style.position='absolute';svg.style.left='48px';svg.style.top='0';svg.style.width='calc(100% - 48px)';svg.style.height='500px';svg.style.pointerEvents='none';document.getElementById('workspace').appendChild(svg);
function xy(d){return[chart.timeScale().timeToCoordinate(d.t),cs.priceToCoordinate(d.p)]}function renderDrawings(){while(svg.firstChild)svg.removeChild(svg.firstChild);drawings.forEach(d=>{if(d.type==='hline'){let y=cs.priceToCoordinate(d.p);if(y==null)return;let e=document.createElementNS(svg.namespaceURI,'line');e.setAttribute('x1',0);e.setAttribute('x2','100%');e.setAttribute('y1',y);e.setAttribute('y2',y);e.setAttribute('stroke','#38bdf8');e.setAttribute('stroke-width','2');e.setAttribute('stroke-dasharray','8 5');svg.appendChild(e)}else if(d.type==='vline'){let x=chart.timeScale().timeToCoordinate(d.t);if(x==null)return;let e=document.createElementNS(svg.namespaceURI,'line');e.setAttribute('x1',x);e.setAttribute('x2',x);e.setAttribute('y1',0);e.setAttribute('y2',500);e.setAttribute('stroke','#a78bfa');e.setAttribute('stroke-width','1.5');e.setAttribute('stroke-dasharray','6 5');svg.appendChild(e)}else{let a=xy(d.a),b=xy(d.b);if(a[0]==null||b[0]==null||a[1]==null||b[1]==null)return;if(d.type==='trend'||d.type==='ray'){let e=document.createElementNS(svg.namespaceURI,'line');let x2=b[0],y2=b[1];if(d.type==='ray'&&Math.abs(b[0]-a[0])>.1){x2=b[0]>a[0]?svg.clientWidth:0;y2=a[1]+(x2-a[0])*(b[1]-a[1])/(b[0]-a[0])}e.setAttribute('x1',a[0]);e.setAttribute('y1',a[1]);e.setAttribute('x2',x2);e.setAttribute('y2',y2);e.setAttribute('stroke','#f59e0b');e.setAttribute('stroke-width','2');svg.appendChild(e)}else if(d.type==='zone'){let e=document.createElementNS(svg.namespaceURI,'rect');e.setAttribute('x',Math.min(a[0],b[0]));e.setAttribute('y',Math.min(a[1],b[1]));e.setAttribute('width',Math.abs(a[0]-b[0]));e.setAttribute('height',Math.abs(a[1]-b[1]));e.setAttribute('fill','#38bdf820');e.setAttribute('stroke','#38bdf8');e.setAttribute('stroke-dasharray','6 4');svg.appendChild(e)}else if(d.type==='fib'){let y1=a[1],y2=b[1],x1=Math.min(a[0],b[0]),x2=Math.max(a[0],b[0]),diff=b[1]-a[1];[0,.236,.382,.5,.618,.786,1].forEach(q=>{let y=y1+diff*q,e=document.createElementNS(svg.namespaceURI,'line');e.setAttribute('x1',x1);e.setAttribute('x2',x2);e.setAttribute('y1',y);e.setAttribute('y2',y);e.setAttribute('stroke','#a78bfa');e.setAttribute('stroke-width','1');svg.appendChild(e)})}}});localStorage.setItem(KEY,JSON.stringify(drawings))}
function point(ev){let r=mainEl.getBoundingClientRect(),x=ev.clientX-r.left,y=ev.clientY-r.top;return{t:chart.timeScale().coordinateToTime(x),p:cs.coordinateToPrice(y)}}mainEl.addEventListener('click',ev=>{if(!mode)return;let q=point(ev);if(!q.t||q.p==null)return;if(mode==='hline'){drawings.push({type:'hline',p:q.p});mode=null}else if(mode==='vline'){drawings.push({type:'vline',t:q.t});mode=null}else if(!pending)pending=q;else{drawings.push({type:mode,a:pending,b:q});pending=null;mode=null}drawMode(mode);renderDrawings()});function drawMode(m){mode=m;pending=null;document.querySelectorAll('.left button').forEach(x=>x.classList.remove('on'));document.getElementById(m||'cursor').classList.add('on');document.getElementById('modeLabel').textContent=m?m.toUpperCase():'Cursor';document.getElementById('hint').textContent=m?'Click '+(m==='hline'?'one price':m==='vline'?'one time point':'two points')+' on the chart.':'TradingView-style workspace • choose a drawing tool or indicator.'}function undo(){drawings.pop();renderDrawings()}function clearDrawings(){drawings=[];renderDrawings()}
// Browser-side live bridge. The iframe owns the price loop.
 // Streamlit never needs to rebuild this chart for a tick.
 let liveBar=null,lastLiveAt=0,followLive=true,lastServerPrice=0;
 mainEl.addEventListener('wheel',()=>{followLive=false},{passive:true});
 function applyLiveTick(t){
   const price=Number(t.price||t.last_price||0), volume=Number(t.volume||0);
   if(!price)return;
   const ts=Math.floor(Number(t.ts||Date.now())/1000);
   lastLiveAt=Date.now(); lastServerPrice=price;
   const bucketSeconds=Math.max(60,Number(TF_MINUTES||5)*60), bucket=ts-ts%bucketSeconds;
   const last=DATA.length?DATA[DATA.length-1]:null;
   if(!liveBar || liveBar.time!==bucket){
     const base=(last&&Number(last.time)===bucket)?last:null;
     liveBar={time:bucket,open:base?Number(base.open):price,high:base?Math.max(Number(base.high),price):price,
              low:base?Math.min(Number(base.low),price):price,close:price,volume:volume||0};
     if(!DATA.length||Number(DATA[DATA.length-1].time)<bucket) DATA.push(liveBar); else DATA[DATA.length-1]=liveBar;
   }else{
     liveBar.close=price; liveBar.high=Math.max(Number(liveBar.high||price),price);
     liveBar.low=Math.min(Number(liveBar.low||price),price);
     if(volume) liveBar.volume=volume;
     if(DATA.length) DATA[DATA.length-1]=liveBar;
   }
   try{
     cs.update(liveBar);
     ls.update({time:bucket,value:price});
     if(overlays.ema20){const e=ema(20);overlays.ema20.update(e[e.length-1]);}
     if(overlays.ema50){const e=ema(50);overlays.ema50.update(e[e.length-1]);}
     if(overlays.sma20){const e=sma(20);overlays.sma20.update(e[e.length-1]);}
     if(overlays.sma50){const e=sma(50);overlays.sma50.update(e[e.length-1]);}
     if(overlays.vwap){let pv=0,v=0;DATA.forEach(x=>{pv+=(x.high+x.low+x.close)/3*(x.volume||0);v+=x.volume||0});overlays.vwap.update({time:bucket,value:v?pv/v:price});}
     vol.update({time:bucket,value:Number(liveBar.volume||0),color:liveBar.close>=liveBar.open?'#22a06b80':'#e0525d80'});
     if(followLive) chart.timeScale().scrollToRealTime();
   }catch(e){}
   const badge=document.querySelector('.live');
   if(badge){badge.textContent='● LIVE '+price.toLocaleString('en-IN',{maximumFractionDigits:2});badge.style.color='#087443';}
 }
 async function supabaseLatest(){
   const SB_URL=__SB_URL__,SB_KEY=__SB_KEY__;
   if(!SB_URL||!SB_KEY)return false;
   try{
     const url=SB_URL+'/rest/v1/live_ticks?symbol=eq.'+encodeURIComponent(LIVE_SYMBOL)+'&select=ts,price&order=ts.desc&limit=1';
     const r=await fetch(url,{headers:{apikey:SB_KEY,Authorization:'Bearer '+SB_KEY},cache:'no-store'});
     if(!r.ok)throw new Error('HTTP '+r.status);
     const a=await r.json();
     if(a&&a.length){
       const ts=new Date(a[0].ts).getTime();
       if(ts>lastLiveAt) applyLiveTick({price:a[0].price,ts});
       return true;
     }
   }catch(e){}
   return false;
 }
 async function startRealtime(){
   const SB_URL=__SB_URL__,SB_KEY=__SB_KEY__;
   if(!SB_URL||!SB_KEY){
     const badge=document.querySelector('.live');
     if(badge){badge.textContent='● SUPABASE REQUIRED';badge.style.color='#b45309';}
     return;
   }
   try{
     if(window.supabaseClient)return;
     const channelName='live-chart-'+LIVE_SYMBOL.replace(/[^a-zA-Z0-9]/g,'-');
     const client=window.supabase.createClient(SB_URL,SB_KEY,{realtime:{params:{eventsPerSecond:10}}});
     window.supabaseClient=client;
     const channel=client.channel(channelName)
       .on('postgres_changes',{event:'INSERT',schema:'public',table:'live_ticks'},
           payload=>{if(payload&&payload.new&&payload.new.symbol===LIVE_SYMBOL)applyLiveTick(payload.new);})
       .subscribe(status=>{
         const badge=document.querySelector('.live');
         if(status==='SUBSCRIBED' && badge) badge.textContent=lastServerPrice?'● LIVE '+lastServerPrice.toLocaleString('en-IN',{maximumFractionDigits:2}):'● LIVE';
         if(status==='CHANNEL_ERROR' || status==='TIMED_OUT') supabaseLatest();
       });
     window.supabaseChannel=channel;
     await supabaseLatest();
   }catch(e){await supabaseLatest();}
 }
 setInterval(()=>{if(!lastLiveAt||Date.now()-lastLiveAt>1400)supabaseLatest()},1000);
 startRealtime();
addLine('ema20',ema(20),'#60a5fa');setPane('RSI');fit();renderDrawings();new ResizeObserver(()=>{chart.applyOptions({width:mainEl.clientWidth});pane.applyOptions({width:paneEl.clientWidth});volChart.applyOptions({width:volEl.clientWidth});renderDrawings()}).observe(mainEl);chart.timeScale().subscribeVisibleTimeRangeChange(()=>{renderDrawings();try{let r=chart.timeScale().getVisibleRange();if(r){volChart.timeScale().setVisibleRange(r);pane.timeScale().setVisibleRange(r)}}catch(e){}});
</script></body></html>'''
    html=html.replace('__DATA__',payload).replace('__LEVELS__',lvl).replace('__TF_MINUTES__',tf).replace('__NAME__',str(name).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')).replace('__NAME_JSON__',nm).replace('__SB_URL__',sb_url_json).replace('__SB_KEY__',sb_key_json).replace('__LIVE_SYMBOL__',live_symbol_json)
    components.html(html,height=775,scrolling=False)

def build_chart_level_payload(levels, spot):
    """Return only meaningful, ranked live support/resistance levels for the price chart."""
    try:
        spot=float(spot)
    except Exception:
        return {"support": [], "resistance": []}

    # Reuse lifecycle engine so chart state matches the level map.
    life=_level_lifecycle_engine(levels, spot)
    payload={"support": [], "resistance": []}

    for side in ("support","resistance"):
        for x in life.get(side, [])[:3]:
            # Broken historical levels are not plotted as active trading levels.
            if x.get("state") == "BROKEN":
                continue
            payload[side].append({
                "structural": float(x["structural"]),
                "precision": float(x["precision"]),
                "state": x.get("state","ACTIVE"),
                "distance": float(x.get("distance",0)),
                "tests": int(x.get("tests",0)),
            })
    return payload

def render_live_level_chart(ohlc, spot, levels, title="Live Price + Levels"):
    """
    Plot the price series with live, calculated support/resistance.
    Uses Plotly when available; gracefully falls back to a table if not.
    """
    import streamlit as st
    payload=build_chart_level_payload(levels, spot)

    try:
        import pandas as pd
        import plotly.graph_objects as go

        d=ohlc.copy() if hasattr(ohlc,"copy") else pd.DataFrame(ohlc)
        if not d.empty:
            fig=go.Figure()
            if {"Open","High","Low","Close"}.issubset(d.columns):
                fig.add_trace(go.Candlestick(
                    x=d.index, open=d["Open"], high=d["High"],
                    low=d["Low"], close=d["Close"], name="Price"
                ))
            elif "close" in d.columns:
                fig.add_trace(go.Scatter(x=d.index,y=d["close"],mode="lines",name="Price"))
            elif "Close" in d.columns:
                fig.add_trace(go.Scatter(x=d.index,y=d["Close"],mode="lines",name="Price"))

            for side in ("support","resistance"):
                for x in payload[side]:
                    val=x["precision"]
                    label=("S" if side=="support" else "R") + f" {val:,.2f}"
                    fig.add_hline(
                        y=val, line_width=2,
                        line_dash="solid" if x["state"] in ("ACTIVE","TESTING","FLIPPED") else "dot",
                        annotation_text=label,
                        annotation_position="bottom left" if side=="support" else "top left"
                    )
                    # Structural strike as a lighter companion.
                    if abs(x["structural"]-val) > 0.01:
                        fig.add_hline(
                            y=x["structural"], line_width=1, line_dash="dot",
                            annotation_text=f"Structural {x['structural']:,.0f}",
                            annotation_position="bottom right" if side=="support" else "top right"
                        )

            fig.add_hline(y=float(spot), line_width=1, line_dash="dash",
                          annotation_text=f"LTP {float(spot):,.2f}",
                          annotation_position="top right")
            fig.update_layout(
                title=title,
                height=520,
                margin=dict(l=10,r=10,t=45,b=10),
                xaxis_rangeslider_visible=False,
                hovermode="x unified",
                legend=dict(orientation="h")
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
            return
    except Exception:
        pass

    # Fallback: readable live level table.
    rows=[]
    for side in ("support","resistance"):
        for x in payload[side]:
            rows.append({
                "Type":side.upper(),
                "State":x["state"],
                "Structural":round(x["structural"],2),
                "Precision":round(x["precision"],2),
                "Distance":round(x["distance"],1)
            })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)

def _safe_num(x, default=None):
    try:
        v=float(x)
        if not (v == v) or v in (float("inf"), float("-inf")):
            return default
        return v
    except Exception:
        return default

def _level_lifecycle_engine(levels, spot, df=None, now=None):
    """
    Turns structural/precision levels into stable intraday states:
    ACTIVE -> TESTING -> BROKEN -> FLIPPED / HISTORICAL.
    It intentionally requires confirmation before declaring a break.
    Returns a dict suitable for rendering and session history.
    """
    import time as _time
    spot=_safe_num(spot)
    if spot is None:
        return {"support": [], "resistance": [], "history": []}

    now = now or _time.time()
    out={"support": [], "resistance": [], "history": []}

    def norm_side(side):
        return "support" if str(side).lower().startswith("s") else "resistance"

    # Accept common level dict formats used by the app.
    candidates=[]
    if isinstance(levels, dict):
        # The authoritative chart levels are the filtered OI-wall arrays.
        # Also include EOS/EOR as a fallback so the chart never silently loses
        # its primary decision anchors.
        for side_key in ("support", "resistance"):
            vals = levels.get(side_key, [])
            if isinstance(vals, (list, tuple)):
                for v in vals:
                    if isinstance(v, dict):
                        d=dict(v)
                        d.setdefault("side", side_key)
                        candidates.append(d)
        for k,v in levels.items():
            if k in ("support", "resistance"):
                continue
            if isinstance(v,(int,float,np.integer,np.floating)):
                candidates.append({"side": "support" if "sup" in str(k).lower() else "resistance",
                                   "structural": v})
            elif isinstance(v,dict):
                d=dict(v)
                d.setdefault("side", "support" if "sup" in str(k).lower() else "resistance")
                candidates.append(d)
    elif isinstance(levels,(list,tuple)):
        for v in levels:
            if isinstance(v,dict):
                candidates.append(dict(v))

    # Session state lives in Streamlit session_state when available.
    try:
        import streamlit as st
        store=st.session_state.setdefault("_level_lifecycle", {})
    except Exception:
        store={}

    for d in candidates:
        side=norm_side(d.get("side", d.get("type","support")))
        structural=_safe_num(d.get("structural", d.get("strike", d.get("level"))))
        precision=_safe_num(d.get("precision", d.get("reversal", d.get("price"))), structural)
        if structural is None:
            continue

        key=f"{side}:{round(structural,2)}"
        state=store.get(key, {"state":"ACTIVE","first_seen":now,"last_seen":now,
                              "tests":0,"break_count":0,"history":[]})
        state["last_seen"]=now

        # Testing proximity: tighter near the level, wider for higher-priced indices.
        proximity=max(4.0, abs(spot)*0.00035)
        distance=spot-precision if side=="support" else precision-spot
        near=abs(distance) <= proximity

        # Confirmed break: penetration beyond precision plus a meaningful buffer.
        # A touch alone remains TESTING.
        break_buffer=max(2.0, abs(spot)*0.00012)
        broken=(spot < precision-break_buffer) if side=="support" else (spot > precision+break_buffer)

        if near and not broken:
            state["tests"] += 1
            if state["state"] not in ("BROKEN","FLIPPED"):
                state["state"]="TESTING"
        elif broken:
            if state["state"] not in ("BROKEN","FLIPPED"):
                state["state"]="BROKEN"
                state["break_count"] += 1
                state["history"].append({"time":now,"event":"BROKEN","price":spot})
            # If price later returns close to the old structural level, mark a flip candidate.
            if abs(spot-structural) <= proximity and state["state"]=="BROKEN":
                state["state"]="FLIPPED"
                state["history"].append({"time":now,"event":"FLIPPED","price":spot})

        store[key]=state

        item={
            "side":side,
            "structural":structural,
            "precision":precision,
            "state":state["state"],
            "distance":abs(spot-precision),
            "tests":state["tests"],
            "break_count":state["break_count"],
        }
        out[side].append(item)

    # Sort nearest first.
    out["support"].sort(key=lambda x: abs(spot-x["precision"]))
    out["resistance"].sort(key=lambda x: abs(spot-x["precision"]))

    # Build compact history.
    for k,v in store.items():
        if v.get("history"):
            out["history"].append({"level":k, **v})
    return out

def render_level_lifecycle(levels, spot, df=None):
    """Readable trader-first level map with broken/next/flip states."""
    import streamlit as st
    life=_level_lifecycle_engine(levels, spot, df)
    st.markdown("### Level Map")

    def card(item):
        state=item["state"]
        icon={"ACTIVE":"🟢","TESTING":"🟡","BROKEN":"🔴","FLIPPED":"🔄"}.get(state,"⚪")
        side=item["side"].upper()
        direction="below spot" if item["side"]=="support" else "above spot"
        st.markdown(
            f"**{icon} {state} — {side}**  \n"
            f"Structural: **{item['structural']:,.2f}** · "
            f"Precision: **{item['precision']:,.2f}** · "
            f"{item['distance']:,.1f} pts {direction}"
        )

    # Current nearest levels
    if life["support"]:
        card(life["support"][0])
    if life["resistance"]:
        card(life["resistance"][0])

    # Explicit next levels after a break.
    broken=[x for x in life["support"]+life["resistance"] if x["state"]=="BROKEN"]
    if broken:
        st.caption("Broken levels remain in history; the next surviving level is shown above.")

    if life["history"]:
        with st.expander("Level history", expanded=False):
            for h in life["history"][-12:]:
                events=h.get("history",[])
                if events:
                    e=events[-1]
                    st.write(f"{h['level']} — {e['event']} @ {e['price']:,.2f}")

def load_upstox_index_catalog():
    found = {}
    errors = []
    for url in INDEX_FILE_URLS:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            raw = r.content
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
            payload = json.loads(raw.decode("utf-8"))
            rows = payload.get("data", payload) if isinstance(payload, dict) else payload
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                seg = str(row.get("segment", ""))
                typ = str(row.get("instrument_type", ""))
                if seg not in ("NSE_INDEX", "BSE_INDEX") or typ != "INDEX":
                    continue
                key = str(row.get("instrument_key", "")).strip()
                name = str(row.get("name") or row.get("trading_symbol") or "").strip()
                if not key or not name:
                    continue
                # Keep the two primary names stable so session state and research files
                # do not split into "Nifty 50" vs "NIFTY 50".
                if key == "NSE_INDEX|Nifty 50":
                    name = "NIFTY 50"
                elif key == "NSE_INDEX|Nifty Bank":
                    name = "BANK NIFTY"
                found[key] = {
                    "name": name,
                    "key": key,
                    "exchange": str(row.get("exchange") or seg.split("_")[0]),
                    "trading_symbol": str(row.get("trading_symbol") or name).strip(),
                    "step": 0,
                    "strike_window": 14,
                }
        except Exception as exc:
            errors.append(str(exc))
    rows = list(found.values())
    rows.sort(key=lambda x: (0 if x["key"] == "NSE_INDEX|Nifty 50" else 1 if x["key"] == "NSE_INDEX|Nifty Bank" else 2, x["name"].upper()))
    return rows, errors

@st.cache_data(ttl=900, show_spinner=False)
def search_index_instruments(query):
    """Public Upstox instrument search for a specific index name/symbol."""
    try:
        r = requests.get(
            f"{API}/instruments/search",
            params={
                "query": query[:50],
                "exchanges": "NSE,BSE",
                "segments": "INDEX",
                "instrument_types": "INDEX",
                "page_number": 1,
                "records": 30,
            },
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        return [
            {
                "name": str(x.get("name") or x.get("trading_symbol") or ""),
                "key": str(x.get("instrument_key") or ""),
                "exchange": str(x.get("exchange") or ""),
                "trading_symbol": str(x.get("trading_symbol") or x.get("name") or ""),
                "step": 0,
                "strike_window": 14,
            }
            for x in (body.get("data") or [])
            if isinstance(x, dict) and x.get("instrument_key")
        ]
    except Exception:
        return []

@st.cache_data(ttl=120, show_spinner=False)
def infer_index_step(token, underlying_key):
    """Infer the actual option strike interval from the nearest active contracts."""
    try:
        d = api_get("/option/contract", token, {"instrument_key": underlying_key})
        rows = d.get("data", []) if isinstance(d, dict) else []
        today = datetime.now(IST).date()
        expiries = []
        for x in rows:
            try:
                e = date.fromisoformat(str(x.get("expiry"))[:10])
                if e >= today:
                    expiries.append(e)
            except Exception:
                pass
        if not expiries:
            return 50
        exp = min(expiries).isoformat()
        strikes = sorted({
            float(x.get("strike_price"))
            for x in rows
            if str(x.get("expiry", ""))[:10] == exp and x.get("strike_price") is not None
        })
        diffs = [b-a for a,b in zip(strikes, strikes[1:]) if b-a > 0]
        if not diffs:
            return 50
        return max(1, int(round(float(pd.Series(diffs).median()))))
    except Exception:
        return 50

def register_index_configs(catalog):
    """Merge discovered indices into the runtime config without disturbing the known two."""
    for meta in catalog:
        name = meta["name"]
        if not name or not meta["key"]:
            continue
        if name not in INDEXES:
            INDEXES[name] = dict(meta)

def index_display_groups():
    names = list(INDEXES.keys())
    preferred = ["NIFTY 50", "BANK NIFTY"]
    first = [x for x in preferred if x in names]
    rest = sorted([x for x in names if x not in preferred], key=str.upper)
    return first + rest



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


@st.cache_data(ttl=180, show_spinner=False)
def previous_session_close(token, key):
    """Return the last completed-session close when the quote does not expose cp."""
    import datetime as _dt
    today = _dt.date.today()
    for back in range(1, 8):
        day = today - _dt.timedelta(days=back)
        ds = day.isoformat()
        try:
            d = api_get3(f"/historical-candle/{quote(key, safe='')}/minutes/1/{ds}/{ds}", token)
            candles = ((d.get("data") or {}).get("candles") or []) if isinstance(d, dict) else []
            if candles:
                return num(candles[-1][4])
        except Exception:
            continue
    return 0.0

def _ws_ltp_for_key(token, key):
    try:
        data, status, error = websocket_pulse(token, [key])
        feed = data.get(key) or data.get(key.replace("|", ":")) if isinstance(data, dict) else None
        if feed is None and isinstance(data, dict) and data:
            feed = next(iter(data.values()))
        vals = ws_extract(feed or {})
        return float(vals.get("ltp") or 0), float(vals.get("cp") or 0), status
    except Exception:
        return 0.0, 0.0, "fallback"

def live_underlying_ltp(token, key):
    """Return live LTP and a stable previous-session close baseline."""
    ltp, cp, status = _ws_ltp_for_key(token, key)
    if ltp <= 0:
        ltp, cp = underlying_ltp(token, key)
        status = "REST"
    baseline = previous_session_close(token, key) if ltp > 0 else 0.0
    if baseline > 0:
        cp = baseline
    return ltp, cp, status

@st.cache_data(ttl=4, show_spinner=False)
def underlying_ltp(token, key):
    data = ltp_quotes(token, key)
    q = quote_from_data(data, key)
    ltp = float(q.get("last_price") or 0)
    cp = float(q.get("cp") or q.get("close_price") or 0)
    if cp <= 0 and ltp > 0:
        cp = previous_session_close(token, key)
    return ltp, cp


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
    """Select *meaningful OI walls*, not simply the nearest strikes.

    A trading level must have evidence on the option chain.  We therefore
    combine raw OI rank, local-peak behaviour, OI strength/pressure and
    distance from spot.  The old implementation always forced the nearest
    strike into the result, which could turn an ordinary-OI strike into a
    fake support/resistance level.
    """
    if d is None or d.empty or spot <= 0 or step <= 0:
        return []

    col = "ce_strength" if side == "resistance" else "pe_strength"
    oi_col = "ce_oi" if side == "resistance" else "pe_oi"
    doi_col = "ce_doi_5m" if side == "resistance" else "pe_doi_5m"
    src = d[d.strike > spot].copy() if side == "resistance" else d[d.strike < spot].copy()
    if src.empty:
        return []

    # Keep the search local enough for intraday trading, but widen it when
    # the nearby chain contains no statistically meaningful OI wall.
    primary = src[(src.strike - spot).abs() <= 8.0 * step].copy()
    if primary.empty:
        primary = src[(src.strike - spot).abs() <= 12.0 * step].copy()
    if primary.empty:
        return []

    primary = primary.sort_values("strike").reset_index(drop=True)
    oi = pd.to_numeric(primary[oi_col], errors="coerce").fillna(0.0).clip(lower=0)
    strength = pd.to_numeric(primary[col], errors="coerce").fillna(0.0).clip(lower=0)
    doi = pd.to_numeric(primary[doi_col], errors="coerce").fillna(0.0)

    # Percentile rank is much more stable than a hard OI number across NIFTY,
    # BANK NIFTY and other indices.  It answers: "is this OI unusually large
    # within the currently relevant chain?"
    oi_pct = oi.rank(pct=True, method="average")
    strength_pct = strength.rank(pct=True, method="average")
    max_oi = float(oi.max()) if len(oi) else 0.0
    max_strength = float(strength.max()) if len(strength) else 0.0
    oi_rel = oi / max(max_oi, 1.0)

    # Local maxima prevent a smooth OI gradient from producing several
    # arbitrary adjacent levels.  A 10% tolerance keeps real OI walls even
    # when neighbouring strikes are almost equal.
    prev_oi = oi.shift(1).fillna(-np.inf)
    next_oi = oi.shift(-1).fillna(-np.inf)
    local_peak = (oi >= prev_oi * 0.90) & (oi >= next_oi * 0.90)

    # A wall normally needs to be in the upper part of the local OI
    # distribution.  The relative-to-max clause avoids rejecting a strong
    # wall when the distribution is unusually flat.
    significant_oi = (oi_pct >= 0.68) & (oi_rel >= 0.45)
    peak_wall = local_peak & (oi_pct >= 0.55) & (oi_rel >= 0.30)
    keep = significant_oi | peak_wall

    # If the chain is exceptionally thin, use the strongest OI observations
    # rather than falling back to the nearest strike.  This still guarantees
    # that every returned level has genuine OI evidence.
    if int(keep.sum()) == 0:
        keep = (oi_pct >= 0.50) & (oi_rel >= 0.25)
    if int(keep.sum()) == 0:
        keep = oi > 0

    candidates = primary.loc[keep].copy()
    if candidates.empty:
        return []

    dist = (candidates["strike"] - spot).abs()
    proximity = np.exp(-dist / max(2.5 * step, 1.0))
    c_oi_pct = oi_pct.loc[candidates.index].to_numpy()
    c_strength_pct = strength_pct.loc[candidates.index].to_numpy()
    c_oi_rel = oi_rel.loc[candidates.index].to_numpy()
    c_doi = doi.loc[candidates.index].to_numpy()
    # Positive OI build gets a modest bonus; it never overrides a weak OI wall.
    doi_scale = max(float(np.nanmax(np.abs(doi.to_numpy()))), 1.0)
    doi_bonus = np.clip(c_doi / doi_scale, -1.0, 1.0)

    candidates["_oi_pct"] = c_oi_pct
    candidates["_oi_rel"] = c_oi_rel
    candidates["_strength_pct"] = c_strength_pct
    candidates["_level_score"] = (
        0.45 * c_oi_pct
        + 0.15 * c_oi_rel
        + 0.10 * c_strength_pct
        + 0.25 * proximity
        + 0.05 * ((doi_bonus + 1.0) / 2.0)
    ) * 100.0

    # Rank by evidence, but for intraday trading give the *nearest strong OI wall*
    # priority. A very large OI wall far away must not hide a meaningful wall
    # immediately below/above spot. This is what keeps a strong 24,300 PE wall
    # visible when spot is 24,366, instead of jumping to 24,200.
    candidates["_near_score"] = np.exp(-(candidates["strike"] - spot).abs() / max(1.75 * step, 1.0))
    candidates["_priority_score"] = (
        0.42 * candidates["_oi_pct"]
        + 0.18 * candidates["_oi_rel"]
        + 0.12 * candidates["_near_score"]
        + 0.10 * candidates["_level_score"] / 100.0
        + 0.08 * candidates["_strength_pct"]
        + 0.10 * ((np.clip(candidates[doi_col], -doi_scale, doi_scale) / max(doi_scale, 1.0)) + 1.0) / 2.0
    )

    # Rank by evidence, then enforce spacing so neighbouring strikes don't all
    # represent the same OI wall.
    candidates = candidates.sort_values(
        ["_priority_score", oi_col], ascending=[False, False]
    )
    chosen = []
    min_gap = max(step * 0.95, 1.0)
    for _, row in candidates.iterrows():
        if all(abs(float(row.strike) - float(q.strike)) >= min_gap for q in chosen):
            chosen.append(row)
        if len(chosen) >= n:
            break

    # Keep chart/table ordering intuitive, but retain the evidence score so
    # calculate_levels can identify the actual primary wall independently.
    chosen = sorted(chosen, key=lambda r: float(r.strike))
    for rank, row in enumerate(sorted(chosen, key=lambda r: float(r["_level_score"]), reverse=True), 1):
        # Series rows are copies; assign rank back by strike for uniqueness.
        for c in chosen:
            if float(c.strike) == float(row.strike):
                c["_level_rank"] = rank
                break
    return chosen


def _reversal_reference_price(row, option_side):
    """Return the option price used for the precise reversal-line calculation.

    The structural level comes from the option-chain strike/OI analysis. The
    precision line is a transparent premium-derived level: support = strike -
    PE premium, resistance = strike + CE premium. LTP is preferred because it
    is the live traded premium; if it is unavailable, a valid bid/ask midpoint
    is used as a fallback.
    """
    if row is None:
        return 0.0, "NONE"
    ltp = float(row.get(f"{option_side}_ltp", 0) or 0)
    if np.isfinite(ltp) and ltp > 0:
        return ltp, "LTP"
    bid = float(row.get(f"{option_side}_bid", 0) or 0)
    ask = float(row.get(f"{option_side}_ask", 0) or 0)
    if np.isfinite(bid) and np.isfinite(ask) and bid > 0 and ask >= bid:
        return (bid + ask) / 2.0, "MID"
    return 0.0, "NONE"


def _precision_reversal(row, side):
    """Calculate a precise, premium-derived reversal line around a strike."""
    if row is None:
        return None, 0.0, "NONE"
    strike = float(row.strike)
    option_side = "pe" if side == "support" else "ce"
    premium, source = _reversal_reference_price(row, option_side)
    if premium <= 0:
        return None, 0.0, source
    level = strike - premium if side == "support" else strike + premium
    return float(level), float(premium), source


def calculate_levels(df, spot, step):
    if df.empty or spot <= 0: return None
    res = pick_levels(df, spot, step, "resistance")
    sup = pick_levels(df, spot, step, "support")

    def primary(rows, side):
        if not rows:
            return None
        # First choose the nearest *statistically strong* wall. This prevents a
        # distant mega-OI strike from suppressing a real intraday decision level.
        near = [r for r in rows if abs(float(r.strike) - spot) <= 2.25 * step]
        if near:
            return max(near, key=lambda r: float(r.get("_priority_score", r.get("_level_score", 0.0))))
        return max(rows, key=lambda r: float(r.get("_priority_score", r.get("_level_score", 0.0))))


    eor_row = primary(res, "resistance")
    eos_row = primary(sup, "support")
    eor = float(eor_row.strike) if eor_row is not None else float(math.ceil(spot/step)*step)
    eos = float(eos_row.strike) if eos_row is not None else float(math.floor(spot/step)*step)

    eos_prec, eos_prem, eos_src = _precision_reversal(eos_row, "support")
    eor_prec, eor_prem, eor_src = _precision_reversal(eor_row, "resistance")

    # The first extension is now the next *strong OI wall*, not merely the
    # adjacent strike. This prevents a low-OI strike from becoming a target.
    sup_ranked = sorted(sup, key=lambda r: float(r.get("_level_score", 0.0)), reverse=True)
    res_ranked = sorted(res, key=lambda r: float(r.get("_level_score", 0.0)), reverse=True)
    eos1_row = next((r for r in sup_ranked if float(r.strike) < eos), None)
    eor1_row = next((r for r in res_ranked if float(r.strike) > eor), None)

    eos1 = float(eos1_row.strike) if eos1_row is not None else eos-step
    eor1 = float(eor1_row.strike) if eor1_row is not None else eor+step
    eos1_prec, eos1_prem, eos1_src = _precision_reversal(eos1_row, "support")
    eor1_prec, eor1_prem, eor1_src = _precision_reversal(eor1_row, "resistance")

    return {
        "eos": eos, "eos1": eos1, "eor": eor, "eor1": eor1,
        "eos_precision": eos_prec, "eor_precision": eor_prec,
        "eos1_precision": eos1_prec, "eor1_precision": eor1_prec,
        "eos_premium": eos_prem, "eor_premium": eor_prem,
        "eos1_premium": eos1_prem, "eor1_premium": eor1_prem,
        "eos_precision_source": eos_src, "eor_precision_source": eor_src,
        "eos1_precision_source": eos1_src, "eor1_precision_source": eor1_src,
        "support": [
            {**r.to_dict(), "side":"support", "structural":float(r.strike),
             "precision": (_precision_reversal(r, "support")[0] or float(r.strike))}
            for r in sup
        ],
        "resistance": [
            {**r.to_dict(), "side":"resistance", "structural":float(r.strike),
             "precision": (_precision_reversal(r, "resistance")[0] or float(r.strike))}
            for r in res
        ],
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
    """Find the nearest active index future using the discovered index metadata."""
    cfg = INDEXES.get(name, {})
    q = str(cfg.get("trading_symbol") or name).strip()
    # Instrument Search is more reliable when the short symbol is used.
    try:
        d = api_get("/instruments/search", token, {
            "query": q[:50], "exchanges": "NSE,BSE", "segments": "FO",
            "instrument_types": "FUT", "expiry": "current_month",
            "page_number": 1, "records": 30,
        })
        rows = d.get("data", []) if isinstance(d, dict) else []
        key = cfg.get("key")
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
    """Process-lifetime Upstox V3 stream.

    The websocket is deliberately independent of Streamlit fragment reruns.
    It also publishes a throttled one-tick-per-second stream to Supabase so the
    browser chart can move without rebuilding the Streamlit component.
    """
    def __init__(self, token, supabase_url="", supabase_key=""):
        self.token=token
        self.lock=threading.Lock()
        self.data={}
        self.status="starting"
        self.error=""
        self.streamer=None
        self.thread=None
        self.keys=[]
        self.supabase_url=supabase_url.rstrip("/") if supabase_url else ""
        self.supabase_key=supabase_key or ""
        self.last_publish={}
        self.last_message_at=0.0
        self.rest_thread=None
        self.rest_stop=threading.Event()
        self.symbol_by_key={str(cfg.get("key")): name for name,cfg in INDEXES.items() if cfg.get("key")}

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

    def _publish_tick(self, key, feed):
        """Publish at most one tick/second/symbol; never let DB failures affect WS."""
        if not self.supabase_url or not self.supabase_key:
            return
        # Indexes keep their friendly names for backward compatibility.
        # Generic futures/options/equities/MCX instruments use the instrument key
        # itself as the stable browser/Supabase symbol.
        symbol=self.symbol_by_key.get(str(key)) or str(key)
        try:
            vals=ws_extract(feed or {})
            price=float(vals.get("ltp") or 0)
            if price <= 0:
                return
            now=datetime.now(IST)
            sec=int(time.time())
            if self.last_publish.get(symbol)==sec:
                return
            self.last_publish[symbol]=sec
            previous_close=float(vals.get("cp") or 0)
            payload=[{
                "symbol":symbol,
                "ts":now.isoformat(),
                "price":_json_number(price),
                "previous_close":_json_number(previous_close)
            }]
            headers={
                "apikey":self.supabase_key,
                "Authorization":f"Bearer {self.supabase_key}",
                "Content-Type":"application/json",
                "Prefer":"return=minimal"
            }
            requests.post(
                f"{self.supabase_url}/rest/v1/live_ticks",
                headers=headers,json=payload,timeout=2
            )
        except Exception:
            pass

    def _on_message(self,message):
        obj=self._normalize(message)
        feeds=obj.get("feeds",{}) if isinstance(obj,dict) else {}
        if not feeds: return
        with self.lock:
            for k,v in feeds.items():
                self.data[k]=v
            self.status="connected"
            self.last_message_at=time.time()
        # Do the HTTP write outside the lock. This is intentionally fire-and-forget
        # from the chart's perspective; the websocket remains the source of truth.
        for k,v in feeds.items():
            self._publish_tick(k,v)

    def _rest_fallback_loop(self):
        while not self.rest_stop.wait(1.0):
            try:
                with self.lock:
                    keys=list(self.keys)
                    stale=(time.time()-float(self.last_message_at or 0)) > 2.5
                if not keys or not stale:
                    continue
                d=api_get("/market-quote/ltp", self.token, {"instrument_key": ",".join(keys)})
                data=d.get("data",{}) if isinstance(d,dict) else {}
                got=0
                for key in keys:
                    q=quote_from_data(data,key)
                    price=float(q.get("last_price") or 0)
                    cp=float(q.get("cp") or q.get("close_price") or 0)
                    if price <= 0:
                        continue
                    feed={"ltpc":{"ltp":price,"cp":cp}}
                    with self.lock:
                        self.data[key]=feed
                        self.status="rest-fallback"
                        self.error="WebSocket stale — V3 LTP fallback active"
                    self._publish_tick(key,feed)
                    got += 1
                if got:
                    with self.lock:
                        self.last_message_at=time.time()
            except Exception as exc:
                with self.lock:
                    self.error=f"REST LTP fallback: {exc}"

    def start(self, keys):
        keys=sorted(set(k for k in keys if k))
        if not keys: return
        with self.lock:
            if self.thread and self.thread.is_alive():
                add=[k for k in keys if k not in self.keys]
                if add and self.streamer:
                    try: self.streamer.subscribe(add,"full")
                    except Exception: pass
                self.keys=sorted(set(self.keys+keys))
                return
            self.keys=keys
        def runner():
            try:
                import upstox_client
                cfg=upstox_client.Configuration(); cfg.access_token=self.token
                self.streamer=upstox_client.MarketDataStreamerV3(
                    upstox_client.ApiClient(cfg), self.keys, "full"
                )
                self.streamer.on("message", self._on_message)
                try: self.streamer.auto_reconnect(True,5,10)
                except Exception: pass
                self.status="connecting"
                self.streamer.connect()
            except Exception as e:
                self.status="fallback"; self.error=str(e)
        self.thread=threading.Thread(target=runner,daemon=True)
        self.thread.start()
        if not self.rest_thread or not self.rest_thread.is_alive():
            self.rest_stop.clear()
            self.rest_thread=threading.Thread(target=self._rest_fallback_loop,daemon=True)
            self.rest_thread.start()

    def snapshot(self):
        with self.lock:
            return dict(self.data), self.status, self.error

@st.cache_resource(show_spinner=False)
def live_feed_resource(token, supabase_url="", supabase_key=""):
    # The websocket is process-lifetime and independent of Streamlit reruns.
    # Supabase credentials are passed once so every server tick can reach the
    # browser without rebuilding the Streamlit component.
    return LiveFeedCache(token, supabase_url, supabase_key)


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
    try:
        sb_url, sb_key = _supabase_config()
        cache=live_feed_resource(token, sb_url, sb_key)
        cache.start(keys)
        data,status,error=cache.snapshot()
        return data,status,error
    except Exception as e:
        return {},"fallback",str(e)


def intraday_phase_label(now=None):
    """Session-aware phase used only to contextualize signals, not to predict direction."""
    now = now or datetime.now(IST)
    t = now.hour * 60 + now.minute
    if t < 9*60+15 or t >= 15*60+30:
        return "OFF HOURS"
    if t < 9*60+30:
        return "OPENING VOLATILITY"
    if t < 11*60:
        return "DISCOVERY / BREAKOUT"
    if t < 13*60:
        return "MIDDAY RANGE"
    if t < 14*60+30:
        return "AFTERNOON REPOSITIONING"
    return "CLOSING FLOW"


def classify_price_oi_flow(df, spot, market, step):
    """Classify price/OI interaction into a small, trader-readable vocabulary."""
    if df is None or df.empty:
        return {"label":"INSUFFICIENT DATA","score":0,"detail":"Option-chain flow is unavailable."}
    r5=float(market.get("ret5",0) or 0)
    ce=float(pd.to_numeric(df.get("ce_doi_5m",0),errors="coerce").fillna(0).sum())
    pe=float(pd.to_numeric(df.get("pe_doi_5m",0),errors="coerce").fillna(0).sum())
    # Positive score = bullish pressure, negative = bearish pressure.
    flow=(pe-ce)/(abs(pe)+abs(ce)+1.0)
    price=np.tanh(r5/0.18)
    score=float(np.clip(55*price+45*flow,-100,100))
    if r5>0.05 and pe>0 and pe>abs(ce)*0.9:
        label="BULLISH BUILD / PUT SUPPORT"
        detail="Price is rising while put-side OI is building faster."
    elif r5< -0.05 and ce>0 and ce>abs(pe)*0.9:
        label="BEARISH BUILD / CALL PRESSURE"
        detail="Price is falling while call-side OI is building faster."
    elif r5>0.05 and ce<0:
        label="SHORT COVERING / RESISTANCE UNWIND"
        detail="Price is rising while call OI is unwinding."
    elif r5< -0.05 and pe<0:
        label="LONG UNWIND / SUPPORT AT RISK"
        detail="Price is falling while put OI is unwinding."
    elif abs(r5)<0.05 and abs(pe-ce)>0:
        label="POSITIONING / PRICE NEUTRAL"
        detail="OI is shifting without a decisive underlying move."
    else:
        label="MIXED FLOW"
        detail="Price and OI do not yet form a clean directional combination."
    return {"label":label,"score":score,"detail":detail,"ce_doi":ce,"pe_doi":pe}


def update_oi_wall_history(index_name, levels, spot, step):
    """Track persistence, tests and migration of the strongest live OI walls."""
    key=f"oi_wall_history_{index_name}"
    hist=st.session_state.setdefault(key,{})
    now=datetime.now(IST)
    current=[]
    for side in ("support","resistance"):
        for r in (levels.get(side) or [])[:4]:
            strike=float(r.get("strike",r.get("structural",0)))
            if not strike: continue
            oi=float(r.get("pe_oi" if side=="support" else "ce_oi",0) or 0)
            strength=float(r.get("pe_strength" if side=="support" else "ce_strength",0) or 0)
            k=f"{side}:{strike:.4f}"
            e=hist.setdefault(k,{"side":side,"strike":strike,"first_seen":now.isoformat(),"last_seen":now.isoformat(),"observations":0,"tests":0,"last_spot":spot,"last_oi":oi,"max_oi":oi,"max_strength":strength})
            e["last_seen"]=now.isoformat(); e["observations"]+=1; e["last_oi"]=oi; e["max_oi"]=max(e.get("max_oi",oi),oi); e["max_strength"]=max(e.get("max_strength",strength),strength)
            prev=e.get("last_spot",spot)
            near_now=abs(spot-strike)<=0.8*step
            near_prev=abs(prev-strike)<=0.8*step
            if near_now and not near_prev: e["tests"]+=1
            if near_prev and not near_now:
                # Reaction = price moved away from the wall after a test.
                if abs(spot-strike)>=1.15*step: e["reactions"]=e.get("reactions",0)+1
            e["last_spot"]=spot
            current.append(e)
    # Keep recent wall records only.
    cutoff=now-timedelta(hours=8)
    cleaned={}
    for k,e in hist.items():
        try: last=datetime.fromisoformat(e["last_seen"])
        except Exception: last=now
        if last>=cutoff: cleaned[k]=e
    st.session_state[key]=cleaned
    # migration: compare today's strongest strike with the prior pulse.
    prev_key=f"oi_wall_prev_{index_name}"
    prev=st.session_state.get(prev_key,{})
    cur={x["side"]:x["strike"] for x in current if x["side"] in ("support","resistance")}
    migration=[]
    for side in ("support","resistance"):
        if side in prev and side in cur and cur[side]!=prev[side]:
            direction="up" if cur[side]>prev[side] else "down"
            migration.append(f"{side.title()} migrated {prev[side]:,.0f} → {cur[side]:,.0f} ({direction})")
    st.session_state[prev_key]=cur
    return current,migration


def update_break_retest_state(index_name, levels, spot, step):
    """Detect confirmed break, retest and hold/failure without declaring a break on one tick."""
    key=f"break_retest_{index_name}"
    store=st.session_state.setdefault(key,{})
    out=[]
    for side in ("support","resistance"):
        active=(levels.get(side) or [])[:2]
        for r in active:
            level=float(r.get("strike",r.get("structural",0)))
            if not level: continue
            k=f"{side}:{level:.4f}"
            e=store.setdefault(k,{"state":"ACTIVE","below_count":0,"above_count":0,"break_price":None,"retest_count":0,"last":spot})
            if side=="support":
                if spot < level-step*0.18: e["below_count"]+=1
                else: e["below_count"]=0
                if e["below_count"]>=2 and e["state"]=="ACTIVE":
                    e["state"]="BROKEN_PENDING_RETEST"; e["break_price"]=spot
                if e["state"]=="BROKEN_PENDING_RETEST" and abs(spot-level)<=step*0.35:
                    e["retest_count"]+=1
                    if spot>level+step*0.08: e["state"]="RETEST_HOLD_FAILED_BREAK"
            else:
                if spot > level+step*0.18: e["above_count"]+=1
                else: e["above_count"]=0
                if e["above_count"]>=2 and e["state"]=="ACTIVE":
                    e["state"]="BROKEN_PENDING_RETEST"; e["break_price"]=spot
                if e["state"]=="BROKEN_PENDING_RETEST" and abs(spot-level)<=step*0.35:
                    e["retest_count"]+=1
                    if spot<level-step*0.08: e["state"]="RETEST_HOLD_FAILED_BREAK"
            e["last"]=spot
            if e["state"]!="ACTIVE": out.append({"side":side,"level":level,**e})
    # Remove stale states when the structural level changes materially.
    if len(store)>40:
        for k in list(store)[:-40]: store.pop(k,None)
    return out



def level_health(index_name, levels):
    """Human-readable strength/invalidation state for active OI walls."""
    hist=st.session_state.get(f"oi_wall_history_{index_name}",{})
    rows=[]
    for side in ("support","resistance"):
        oi_key="pe_oi" if side=="support" else "ce_oi"
        doi_key="pe_doi_5m" if side=="support" else "ce_doi_5m"
        strength_key="pe_strength" if side=="support" else "ce_strength"
        for r in (levels.get(side) or [])[:3]:
            strike=float(r.get("strike",r.get("structural",0)))
            if not strike: continue
            e=hist.get(f"{side}:{strike:.4f}",{})
            oi=float(r.get(oi_key,0) or 0); strength=float(r.get(strength_key,0) or 0); doi=float(r.get(doi_key,0) or 0)
            max_oi=float(e.get("max_oi",oi) or oi)
            persistence=int(e.get("observations",0) or 0)
            oi_retention=oi/max(max_oi,1.0)
            health=100*(0.55*max(0,min(1,oi_retention))+0.25*max(0,min(1,strength/100))+0.20*max(0,min(1,persistence/12)))
            if oi_retention<0.55 or (doi<0 and oi_retention<0.75): state="WEAKENING"
            elif persistence>=6 and oi_retention>=0.85: state="PERSISTENT"
            else: state="ACTIVE"
            rows.append({"Side":side.title(),"Level":strike,"Health":round(health),"State":state,"OI":oi,"ΔOI 5m":doi,"Pulses":persistence})
    return pd.DataFrame(rows)


def auto_calibration_report():
    """Empirical calibration table for directional model score buckets."""
    rows=st.session_state.get("auto_snapshots",[])
    if len(rows)<60: return None
    d=pd.DataFrame(rows)
    if d.empty: return None
    d["ts_dt"]=pd.to_datetime(d["timestamp"])
    results=[]
    for i,row in d.iterrows():
        later=d[(d.ts_dt>row.ts_dt)&(d["index"]==row["index"])]
        if later.empty: continue
        target=row.ts_dt+pd.Timedelta(minutes=15)
        q=later.iloc[(later.ts_dt-target).abs().argsort()[:1]]
        if q.empty: continue
        ret=(float(q.spot.iloc[0])/float(row.spot)-1)*100
        score=float(row.model)
        if abs(score)<10: continue
        correct=int((score>0 and ret>0) or (score<0 and ret<0))
        mag=abs(score)
        bucket="10–24" if mag<25 else "25–49" if mag<50 else "50–74" if mag<75 else "75–100"
        results.append({"Bucket":bucket,"Correct":correct,"Return":ret})
    if not results: return None
    r=pd.DataFrame(results)
    out=r.groupby("Bucket").agg(Samples=("Correct","size"),Observed_hit_rate=("Correct","mean"),Mean_15m_return=("Return","mean")).reset_index()
    order={"10–24":0,"25–49":1,"50–74":2,"75–100":3}
    return out.assign(_o=out.Bucket.map(order)).sort_values("_o").drop(columns="_o")

def level_history_summary(index_name, levels):
    hist=st.session_state.get(f"oi_wall_history_{index_name}",{})
    rows=[]
    for side in ("support","resistance"):
        for r in (levels.get(side) or [])[:3]:
            strike=float(r.get("strike",r.get("structural",0)))
            e=hist.get(f"{side}:{strike:.4f}",{})
            if not e: continue
            try: age=(datetime.now(IST)-datetime.fromisoformat(e["first_seen"])).total_seconds()/60
            except Exception: age=0
            rows.append({"side":side,"strike":strike,"age_min":max(0,age),"observations":e.get("observations",0),"tests":e.get("tests",0),"reactions":e.get("reactions",0),"oi":e.get("last_oi",0)})
    return pd.DataFrame(rows)


def research_false_break_stats():
    rows=st.session_state.get("auto_snapshots",[])
    if len(rows)<30: return None
    d=pd.DataFrame(rows)
    if d.empty or "failed_break" not in d: return None
    d["phase"]=d["timestamp"].apply(lambda x: intraday_phase_label(datetime.strptime(x,"%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)))
    return d.groupby("phase").agg(snapshots=("failed_break","size"),failed_break_rate=("failed_break","mean"),avg_model=("model","mean")).reset_index()

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
        "regime":regime.get("regime",""), "phase":intraday_phase_label(),
        "failed_break":1 if events.get("failed_breakout","NONE")!="NONE" else 0,
    })
    # Keep memory bounded for long browser sessions.
    st.session_state[key]=rows[-5000:]


def render_auto_backtest():
    st.markdown("## 📚 Auto-captured Session Research")
    rows=st.session_state.get("auto_snapshots",[])
    if not rows:
        st.info("No automatic snapshots yet. The live terminal records model states during live updates.")
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
    status = "NO TRADE" if setup["no_trade"] else "TRADEABLE"
    timing = "WAIT" if setup["trigger"] is None else ("TRIGGERED" if abs(spot-setup["trigger"]) <= step*0.15 else "WATCH")
    st.markdown(f"<div class='setup-strip'><span><b>STATE</b> {status}</span><span><b>TIMING</b> {timing}</span><span><b>REGIME</b> {regime.get('regime','—')}</span><span><b>LEVEL</b> {'EOS' if 'DOWN' in setup['setup'].upper() else 'EOR' if 'UP' in setup['setup'].upper() else 'BAND'}</span></div>", unsafe_allow_html=True)

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

def render_index_overview(name, token):
    """Index-only view for instruments without a usable option chain."""
    cfg = INDEXES[name]
    try:
        spot, cp = underlying_ltp(token, cfg["key"])
        market = session_market_metrics(token, cfg["key"])
    except Exception as exc:
        st.error(f"{name}: market data unavailable: {exc}")
        return
    change_pct = (spot / cp - 1) * 100 if cp else 0.0
    vwap = float(market.get("vwap", 0) or 0)
    ret5 = float(market.get("ret5", 0) or 0)
    ret15 = float(market.get("ret15", 0) or 0)
    bias = "UPTREND" if spot > vwap and ret5 >= 0 else "DOWNTREND" if vwap and spot < vwap and ret5 <= 0 else "TRANSITION / RANGE"
    cls = "bull" if bias == "UPTREND" else "bear" if bias == "DOWNTREND" else "range"
    st.markdown(f"## {name} <span style='font-size:12px;color:#64748b;font-weight:500'>• index-only analytics • live analytics</span>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class="trader-shell">
      <div class="decision">
        <div class="box {cls}"><div class="label">Market state</div><div class="big">{'🟢' if cls=='bull' else '🔴' if cls=='bear' else '🟡'} {bias}</div><div class="sub">Price structure only — no option chain available</div></div>
        <div class="box"><div class="label">Spot</div><div class="big">{spot:,.2f}</div><div class="sub">{change_pct:+.2f}% today</div></div>
        <div class="box"><div class="label">VWAP</div><div class="big">{vwap:,.2f}</div><div class="sub">{spot-vwap:+.0f} pts vs VWAP</div></div>
        <div class="box"><div class="label">Intraday momentum</div><div class="big" style="font-size:19px">5m {ret5:+.2f}% · 15m {ret15:+.2f}%</div><div class="sub">No derivative inference is made</div></div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    m1,m2,m3,m4,m5,m6=st.columns(6)
    m1.metric("Opening range", f"{market.get('or_low',0):,.0f}–{market.get('or_high',0):,.0f}")
    m2.metric("Session high", f"{market.get('session_high',0):,.0f}")
    m3.metric("Session low", f"{market.get('session_low',0):,.0f}")
    m4.metric("5m", f"{ret5:+.2f}%")
    m5.metric("15m", f"{ret15:+.2f}%")
    m6.metric("Data mode", "INDEX ONLY")
    st.info("This index is available through Upstox market data, but the current option-chain endpoint did not return a usable expiry. The terminal therefore avoids inventing OI/EOS/EOR analytics.")
    st.markdown("### 📍 Intraday structure")
    if vwap:
        st.write(("🟢" if spot > vwap else "🔴") + f" Spot is {abs(spot-vwap):,.0f} points {'above' if spot>vwap else 'below'} VWAP.")
    st.write(f"Opening range: **{market.get('or_low',0):,.0f} – {market.get('or_high',0):,.0f}**")
    st.write(f"Session range: **{market.get('session_low',0):,.0f} – {market.get('session_high',0):,.0f}**")
    st.caption("For derivatives-enabled indices, selecting the index again after the exchange publishes its option contracts will automatically upgrade the view to the full OI/levels terminal.")

@st.cache_data(ttl=30, show_spinner=False)
def today_one_minute_candles(token, key):
    """Fetch the complete current trading day's 1-minute candle series."""
    import datetime as _dt
    ds = _dt.datetime.now(IST).date().isoformat()
    try:
        d = api_get3(f"/historical-candle/{quote(key, safe='')}/minutes/1/{ds}/{ds}", token)
        candles = ((d.get("data") or {}).get("candles") or []) if isinstance(d, dict) else []
        rows = []
        for c in candles:
            if len(c) < 5:
                continue
            rows.append({"time": str(c[0]), "open": num(c[1]), "high": num(c[2]),
                         "low": num(c[3]), "close": num(c[4]),
                         "volume": num(c[5]) if len(c) > 5 else 0})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["time","open","high","low","close","volume"])

def archive_today_prices(token, names):
    """Archive today's complete 1-minute index candles to Supabase."""
    if not supabase_enabled():
        return {"saved": False, "reason": "Supabase is not configured."}
    total = 0
    for name in names:
        if name not in INDEXES:
            continue
        df = today_one_minute_candles(token, INDEXES[name]["key"])
        if df.empty:
            continue
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "symbol": name,
                "trading_date": datetime.now(IST).date().isoformat(),
                "ts": str(r["time"]),
                "open": _json_number(r["open"]), "high": _json_number(r["high"]),
                "low": _json_number(r["low"]), "close": _json_number(r["close"]),
                "volume": _json_number(r["volume"]),
            })
        ok, n = _post_supabase("price_candles", rows, "symbol,ts")
        total += n
    return {"saved": total > 0, "rows": total}

def publish_live_tick(name, spot, cp=0.0):
    """Publish compact live price ticks for the browser chart."""
    if not supabase_enabled() or not spot:
        return
    now = datetime.now(IST)
    if now.weekday() >= 5 or now.hour < 9 or now.hour > 15 or (now.hour == 15 and now.minute > 30):
        return
    last = st.session_state.setdefault("_live_tick_last", {})
    sec = int(time.time())
    if last.get(name) == sec:
        return
    last[name] = sec
    _post_supabase("live_ticks", [{
        "symbol": name, "ts": now.isoformat(),
        "price": _json_number(spot), "previous_close": _json_number(cp)
    }], None)

def maybe_archive_after_close(token):
    now=datetime.now(IST)
    if now.weekday()>=5 or (now.hour,now.minute)<(15,31):
        return
    if st.session_state.get("_today_archive_done"):
        return
    st.session_state["_today_archive_done"]=True
    try:
        result=archive_today_prices(token, ["NIFTY 50","BANK NIFTY"])
        st.session_state["_today_archive_result"]=result
    except Exception as exc:
        st.session_state["_today_archive_result"]={"saved":False,"reason":str(exc)}

def render_index_v3(name, token, include_chart=True):

    """Trader-first presentation layer over the existing V4 analytics engine."""
    cfg = INDEXES[name]
    # Discover the real strike interval for dynamically added indices.
    if not cfg.get("step"):
        cfg["step"] = infer_index_step(token, cfg["key"])
    try:
        spot, cp, live_mode = live_underlying_ltp(token, cfg["key"])
        contracts = option_contracts(token, cfg["key"])
        expiry = nearest_expiry(contracts)
        if not expiry:
            render_index_overview(name, token)
            return
        chain = option_chain(token, cfg["key"], expiry)
        df = enrich_tick(build_option_df(chain), name)
    except Exception as e:
        # A selected index should remain usable even when its derivatives endpoint
        # is unavailable; fall back to clean index-only analytics.
        try:
            render_index_overview(name, token)
        except Exception:
            st.error(f"{name}: {e}")
        return

    if df.empty:
        render_index_overview(name, token)
        return

    df = enrich_advanced(df, spot, cfg["step"], name)
    levels = calculate_levels(df, spot, cfg["step"])
    try:
        publish_live_tick(name, spot, cp)
    except Exception:
        pass

    if include_chart:
        # ---------------- UPSTOX TRADINGVIEW-STYLE CHART ----------------
        # Candles come directly from Upstox V3; level lines come from the same
        # live option-chain level engine used elsewhere on the page.
        try:
            st.markdown("### Price Chart — Upstox Live Data")
            _tf_options = {
                "1m": 1,
                "3m": 3,
                "5m": 5,
                "15m": 15,
                "30m": 30,
                "1H": 60,
            }
            _tf = st.radio(
                "Timeframe",
                list(_tf_options.keys()),
                index=2,
                horizontal=True,
                key=f"tv_tf_{name.replace(' ', '_')}",
            )
            _tv_candles = upstox_intraday_candles_df(
                token, cfg["key"], _tf_options[_tf]
            )
            render_upstox_tv_chart(_tv_candles, spot, levels, name, _tf_options[_tf])
            st.caption("🟢 LIVE — price stream active.")
            st.caption(
                f"Candles: Upstox V3 • {_tf} timeframe • "
                "Levels: live OI-derived precision levels • "
                "On weekends/holidays, the chart shows the latest completed session."
            )
        except Exception as _chart_err:
            st.warning(f"{name}: chart temporarily unavailable — {_chart_err}")
    if levels is None:
        st.error(f"{name}: unable to calculate EOS/EOR from the returned chain.")
        return

    # Research-grade live context: persistence, migration and break/retest state.
    wall_rows, wall_migration = update_oi_wall_history(name, levels, spot, cfg["step"])
    break_retest = update_break_retest_state(name, levels, spot, cfg["step"])
    flow_read = classify_price_oi_flow(df, spot, {}, cfg["step"])

    market = session_market_metrics(token, cfg["key"])
    flow_read = classify_price_oi_flow(df, spot, market, cfg["step"])
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
    # Persist the exact state used by the live engine once per minute.
    try:
        st.session_state["_supabase_last_status"] = save_supabase_minute(
            name, spot, expiry, df, levels, scenario, market, structure,
            futures, regime, events
        )
    except Exception as _db_err:
        # Database persistence must never take down the trading dashboard.
        st.session_state["_supabase_last_status"] = {"enabled": True, "saved": False, "error": str(_db_err)}
    render_supabase_status()

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

    st.markdown(f"## {name} <span style='font-size:12px;color:#64748b;font-weight:500'>• {expiry} • {phase} • <b>{live_mode}</b> live</span>", unsafe_allow_html=True)
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
    # WHAT CHANGED + DISTANCE TO BATTLEFIELD
    # -----------------------------
    st.markdown("## ⚡ What changed in the latest market update")
    change_rows = []
    prev_snapshot = st.session_state.get(f"ui_snapshot_{name}")
    current_snapshot = {
        "spot": float(spot),
        "eor": float(levels["eor"]),
        "eos": float(levels["eos"]),
        "ce_doi": float(dce),
        "pe_doi": float(dpe),
        "vwap": float(vwap or 0),
        "primary": primary,
    }
    if prev_snapshot:
        spot_delta = current_snapshot["spot"] - prev_snapshot["spot"]
        eor_delta = current_snapshot["eor"] - prev_snapshot["eor"]
        eos_delta = current_snapshot["eos"] - prev_snapshot["eos"]
        ce_delta = current_snapshot["ce_doi"] - prev_snapshot["ce_doi"]
        pe_delta = current_snapshot["pe_doi"] - prev_snapshot["pe_doi"]
        if abs(spot_delta) >= max(1, cfg["step"]*0.05):
            change_rows.append(("🟢" if spot_delta>0 else "🔴", f"Spot moved {spot_delta:+.0f} pts"))
        if abs(eor_delta) >= 1:
            change_rows.append(("🔴", f"EOR shifted {eor_delta:+.0f} pts"))
        if abs(eos_delta) >= 1:
            change_rows.append(("🟢", f"EOS shifted {eos_delta:+.0f} pts"))
        if abs(ce_delta) > 0:
            change_rows.append(("🔴" if ce_delta>0 else "🟢", f"Core CE OI {('built' if ce_delta>0 else 'unwound')} {format_oi(abs(ce_delta))}"))
        if abs(pe_delta) > 0:
            change_rows.append(("🟢" if pe_delta>0 else "🔴", f"Core PE OI {('built' if pe_delta>0 else 'unwound')} {format_oi(abs(pe_delta))}"))
        if current_snapshot["primary"] != prev_snapshot.get("primary"):
            change_rows.append(("⚠️", f"Scenario changed {prev_snapshot.get('primary','—')} → {primary}"))
    st.session_state[f"ui_snapshot_{name}"] = current_snapshot
    if change_rows:
        cc=st.columns(min(4,len(change_rows)))
        for i,(icon,text) in enumerate(change_rows[:4]):
            cc[i].markdown(f"<div class='change-card'><div class='change-icon'>{icon}</div><div>{text}</div></div>", unsafe_allow_html=True)
    else:
        st.caption("No material change detected in the latest market update.")

    # -----------------------------
    # OI WALL MEMORY / FLOW / BREAK-RETEST
    # -----------------------------
    st.markdown("## 🧭 Level memory & intraday flow")
    p1,p2,p3,p4=st.columns(4)
    p1.metric("Session phase", intraday_phase_label())
    p2.metric("Flow read", flow_read.get("label","—"))
    p3.metric("Flow score", f"{flow_read.get('score',0):+.0f}")
    p4.metric("Wall migrations", str(len(wall_migration)))
    st.caption(flow_read.get("detail",""))
    if wall_migration:
        for m in wall_migration[:3]: st.info("↔ " + m)
    lh=level_history_summary(name, levels)
    br=pd.DataFrame(break_retest)
    h1,h2=st.columns([1.2,1])
    with h1:
        st.markdown("### OI wall persistence")
        if lh.empty:
            st.caption("Persistence begins accumulating as the live chain updates.")
        else:
            view=lh.copy(); view["Age"] = view.age_min.map(lambda x:f"{x:.0f}m"); view["OI"]=view.oi.map(format_oi)
            st.dataframe(view[["side","strike","Age","observations","tests","reactions","OI"]].rename(columns={"side":"Side","strike":"Level","observations":"Pulses","tests":"Tests","reactions":"Reactions"}),use_container_width=True,hide_index=True)
    with h2:
        st.markdown("### Break / retest monitor")
        if br.empty:
            st.caption("No confirmed multi-pulse break/retest state is active.")
        else:
            bv=br[["side","level","state","retest_count"]].copy()
            bv.columns=["Side","Level","State","Retests"]
            st.dataframe(bv,use_container_width=True,hide_index=True)
    st.markdown("### 🛡️ Level health / invalidation")
    health=level_health(name, levels)
    if health.empty:
        st.caption("Level health will populate after a few market updates.")
    else:
        hv=health.copy(); hv["OI"]=hv["OI"].map(format_oi); hv["ΔOI 5m"]=hv["ΔOI 5m"].map(sign_text)
        st.dataframe(hv[["Side","Level","Health","State","OI","ΔOI 5m","Pulses"]],use_container_width=True,hide_index=True)
    st.caption("Persistence, migration, health and retest states are evidence accumulators; they do not guarantee a trade outcome.")

    # Immediate proximity to the next meaningful level.
    # The strike remains the structural anchor; the premium-derived precision
    # line is shown alongside it so traders can see the exact reversal area.
    candidates = []
    for item in levels.get("support", [])[:2]:
        candidates.append(("SUPPORT", float(item["structural"]), "support"))
    for item in levels.get("resistance", [])[:2]:
        candidates.append(("RESISTANCE", float(item["structural"]), "resistance"))
    if not candidates:
        candidates = [
            ("EOS", float(levels["eos"]), "support"),
            ("EOR", float(levels["eor"]), "resistance"),
        ]
    candidates.sort(key=lambda z: abs(z[1]-spot))
    st.markdown("## 🎯 Nearest meaningful levels")
    if not levels.get("support"):
        st.warning("No nearby support OI wall was returned. The terminal will not invent a support level.")
    if not levels.get("resistance"):
        st.warning("No nearby resistance OI wall was returned. The terminal will not invent a resistance level.")

    lc=st.columns(min(4,len(candidates)))
    for i,(lab,price,side) in enumerate(candidates):
        dist=price-spot
        icon="🟢" if side=="support" else "🔴"
        lc[i].markdown(f"<div class='proximity-card'><div class='prox-head'>{icon} {lab} · {side}</div><div class='prox-price'>{price:,.0f}</div><div class='prox-dist'>{dist:+,.0f} pts from spot</div></div>", unsafe_allow_html=True)

    # -----------------------------
    # PRECISION REVERSAL LINES
    # -----------------------------
    st.markdown("## 🎯 Precision reversal lines")
    st.caption("Structural support/resistance comes from the strongest nearby OI strike. The exact line is a transparent option-premium calculation: support = strike − PE premium; resistance = strike + CE premium. It is an analytical level, not a guaranteed reversal.")
    pc1, pc2 = st.columns(2)
    with pc1:
        if levels.get("eos_precision") is not None:
            st.markdown(f"""
            <div class='precision-card support-precision'>
              <div class='precision-label'>🟢 SUPPORT REVERSAL</div>
              <div class='precision-main'>{levels['eos_precision']:,.2f}</div>
              <div class='precision-sub'>Structural EOS {levels['eos']:,.0f} − PE premium ₹{levels['eos_premium']:,.2f} · {levels.get('eos_precision_source','LTP')}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info(f"EOS structural level: {levels['eos']:,.0f}. A precise premium-derived line is unavailable because the relevant PE premium is missing.")
    with pc2:
        if levels.get("eor_precision") is not None:
            st.markdown(f"""
            <div class='precision-card resistance-precision'>
              <div class='precision-label'>🔴 RESISTANCE REVERSAL</div>
              <div class='precision-main'>{levels['eor_precision']:,.2f}</div>
              <div class='precision-sub'>Structural EOR {levels['eor']:,.0f} + CE premium ₹{levels['eor_premium']:,.2f} · {levels.get('eor_precision_source','LTP')}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info(f"EOR structural level: {levels['eor']:,.0f}. A precise premium-derived line is unavailable because the relevant CE premium is missing.")

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
          <div class="lvl ext redlvl"><span>EOR + 1</span><b>{levels["eor1"]:,.0f}</b><small>extension{f" · exact {levels['eor1_precision']:,.2f}" if levels.get('eor1_precision') is not None else ""}</small></div>
          <div class="lvl redlvl"><span>EOR</span><b>{levels["eor"]:,.0f}</b><small>resistance · {levels["resistance_score"]:.0f}/100{f" · exact {levels['eor_precision']:,.2f}" if levels.get('eor_precision') is not None else ""}</small></div>
          <div class="lvl spotlvl"><span>SPOT</span><b>{spot:,.2f}</b><small>current price</small></div>
          <div class="lvl greenlvl"><span>EOS</span><b>{levels["eos"]:,.0f}</b><small>support · {levels["support_score"]:.0f}/100{f" · exact {levels['eos_precision']:,.2f}" if levels.get('eos_precision') is not None else ""}</small></div>
          <div class="lvl ext greenlvl"><span>EOS − 1</span><b>{levels["eos1"]:,.0f}</b><small>extension{f" · exact {levels['eos1_precision']:,.2f}" if levels.get('eos1_precision') is not None else ""}</small></div>
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
    with st.expander("📊 Quant Details — raw chain, Greeks, official data & diagnostics", expanded=True):
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
    # INDEX DRIVERS: high-value, always visible where methodology is available
    # -----------------------------
    with st.expander(f"🚦 What is moving {name} — index-impact ranking", expanded=True):
        if name in ("NIFTY 50", "BANK NIFTY"):
            render_contributors(token, name)
        else:
            st.info("Index-impact ranking is shown for NIFTY 50 and BANK NIFTY where the terminal has maintained constituent-weight maps. Other indices are not assigned a fake weighting model.")

    # -----------------------------
    # MOVERS + RESEARCH

    # -----------------------------
    with st.expander("📰 Market story", expanded=True):
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
    with st.expander("🎯 Risk map / execution math", expanded=True):
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
        nifty_ltp, nifty_cp, nifty_mode = live_underlying_ltp(token, INDEXES["NIFTY 50"]["key"])
        bank_ltp, bank_cp, bank_mode = live_underlying_ltp(token, INDEXES["BANK NIFTY"]["key"])
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
    cal=auto_calibration_report()
    if cal is not None:
        st.markdown("### 📏 Empirical score calibration (15-minute forward)")
        st.dataframe(cal.style.format({"Observed_hit_rate":"{:.1%}","Mean_15m_return":"{:+.3f}%"}),use_container_width=True,hide_index=True)
        st.caption("This is empirical calibration from captured sessions, not a probability guarantee. It becomes meaningful only after multiple independent market days.")
    fb=research_false_break_stats()
    if fb is not None:
        st.markdown("### False-break rate by session phase")
        st.dataframe(fb.style.format({"failed_break_rate":"{:.1%}","avg_model":"{:+.1f}"}),use_container_width=True,hide_index=True)
        st.caption("These are observed research statistics from captured snapshots, not live probabilities. More independent sessions are required before calibration.")
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
    .change-card{min-height:66px;display:flex;align-items:center;gap:10px;background:#fff;border:1px solid #e5eaf0;border-radius:14px;padding:10px 12px;box-shadow:0 4px 16px rgba(15,23,42,.04);font-size:12px;font-weight:700}
    .change-icon{font-size:19px}.precision-card{border:1px solid #dbe4ee;border-radius:16px;padding:16px 18px;background:#fff;box-shadow:0 6px 20px rgba(15,23,42,.05);min-height:108px}.support-precision{border-left:4px solid #059669}.resistance-precision{border-left:4px solid #dc2626}.precision-label{font-size:11px;font-weight:800;letter-spacing:.08em;color:#64748b}.precision-main{font-size:30px;font-weight:850;line-height:1.15;margin:7px 0;color:#0f172a}.precision-sub{font-size:12px;color:#64748b;line-height:1.45}.proximity-card{background:#fff;border:1px solid #e5eaf0;border-radius:15px;padding:12px 14px;box-shadow:0 5px 18px rgba(15,23,42,.045)}
    .prox-head{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#64748b;font-weight:800}.prox-price{font-size:21px;font-weight:850;color:#172033;margin-top:4px}.prox-dist{font-size:11px;color:#64748b;margin-top:3px}
    .setup-strip{display:flex;gap:10px;flex-wrap:wrap;background:#f8fafc;border:1px solid #e5eaf0;border-radius:12px;padding:9px 12px;margin:8px 0 14px;color:#475569;font-size:11px}
    .setup-strip span{padding-right:10px;border-right:1px solid #dfe5ec}.setup-strip span:last-child{border-right:0}
    .pulse-top{font-size:12px;color:#475569}.pulse-main{font-size:15px;font-weight:800;margin-top:6px}.pulse-sub{font-size:11px;color:#64748b;margin-top:3px}
    .level-stack{display:flex;flex-direction:column;gap:5px}
    .level-stack .lvl{display:grid;grid-template-columns:70px 1fr 1fr;align-items:center;padding:9px 12px;border-radius:10px}
    .level-stack .lvl b{font-size:18px;text-align:center}.level-stack small{text-align:right;color:#64748b}
    .redlvl{background:#fff1f2;color:#9f1239}.greenlvl{background:#ecfdf5;color:#047857}.spotlvl{background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe}
    .ext{opacity:.72}
    @media(max-width:900px){.decision{grid-template-columns:1fr 1fr}.mini-grid{grid-template-columns:repeat(3,1fr)}}
    </style>
    """, unsafe_allow_html=True)


def render_static_live_chart(token, name, tf_minutes=5):
    """Mount the chart once, outside the Streamlit fragment.

    The chart receives one-second Supabase realtime ticks from the process-level
    Upstox websocket. Because this component is not inside the analytics fragment,
    fragment reruns cannot delete/white-out the chart.
    """
    try:
        cfg=INDEXES[name]
        if not cfg.get("step"):
            cfg["step"]=infer_index_step(token,cfg["key"])
        spot, cp, _ = live_underlying_ltp(token,cfg["key"])
        contracts=option_contracts(token,cfg["key"])
        expiry=nearest_expiry(contracts)
        chain=option_chain(token,cfg["key"],expiry) if expiry else []
        df=build_option_df(chain)
        levels=None
        if not df.empty and spot>0:
            # Bootstrap level evidence without touching the pulse_prev_* state.
            df["ce_doi_tick"]=0.0
            df["pe_doi_tick"]=0.0
            df=enrich_advanced(df,spot,cfg["step"],name)
            levels=calculate_levels(df,spot,cfg["step"])
        # Start the process-lifetime V3 feed here. The chart no longer depends
        # on an analytics fragment to keep the websocket alive.
        websocket_pulse(token, [cfg["key"]])
        candles=upstox_intraday_candles_df(token,cfg["key"],tf_minutes)
        if levels is None:
            levels={"support":[],"resistance":[],"eos":spot,"eor":spot,"eos1":spot,"eor1":spot,
                    "eos_precision":None,"eor_precision":None}
        render_upstox_tv_chart(candles,spot,levels,name,tf_minutes,token)
        st.caption("🟢 LIVE — browser chart is fed from the server-side Upstox stream.")
    except Exception as exc:
        st.warning(f"{name}: live chart bootstrap unavailable — {exc}")


@st.cache_data(ttl=20, show_spinner=False)
def search_market_instruments(token, query, exchanges, segments, instrument_types="", expiry=""):
    """Search the Upstox instrument universe for equities, futures, options or MCX."""
    query=str(query or "").strip()
    if not query:
        return []
    params={
        "query": query[:50],
        "exchanges": exchanges,
        "segments": segments,
        "page_number": 1,
        "records": 30,
    }
    if instrument_types:
        params["instrument_types"]=instrument_types
    if expiry:
        params["expiry"]=expiry
    try:
        d=api_get("/instruments/search", token, params)
        rows=d.get("data",[]) if isinstance(d,dict) else []
        return [r for r in rows if isinstance(r,dict) and r.get("instrument_key")]
    except Exception:
        return []


def _market_result_label(row):
    sym=str(row.get("trading_symbol") or row.get("short_name") or row.get("name") or row.get("instrument_key"))
    expiry=str(row.get("expiry") or "")
    typ=str(row.get("instrument_type") or "")
    strike=row.get("strike_price")
    extra=[]
    if typ: extra.append(typ)
    if strike not in (None,"",0,0.0): extra.append(str(strike))
    if expiry: extra.append(expiry[:10])
    return sym + (" • " + " ".join(extra) if extra else "")


def render_generic_market_chart(token, row, tf_minutes=5, title_prefix=""):
    """Render the same browser-live Lightweight Charts workspace for any Upstox instrument."""
    key=str(row.get("instrument_key") or "")
    if not key:
        st.warning("No instrument key was returned by Upstox.")
        return
    # Generic instruments have no OI-derived index levels. Keep the chart clean
    # rather than fabricating support/resistance.
    websocket_pulse(token,[key])
    candles=upstox_intraday_candles_df(token,key,tf_minutes)
    if candles.empty:
        st.warning(f"No intraday candles are available yet for {_market_result_label(row)}.")
        return
    name=str(row.get("trading_symbol") or row.get("short_name") or row.get("name") or key)
    spot, cp, status = live_underlying_ltp(token,key)
    if not spot:
        try:
            q=quote_from_data(ltp_quotes(token,key),key)
            spot=num(q.get("last_price"))
        except Exception:
            spot=float(candles.iloc[-1]["close"])
    levels={"support":[],"resistance":[]}
    render_upstox_tv_chart(
        candles, spot, levels,
        f"{title_prefix}{name}" if title_prefix else name,
        tf_minutes, token, live_symbol=key
    )
    if status:
        st.caption(f"Live transport: {status} • instrument: {key}")


def render_market_explorer(token):
    """Interactive multi-asset explorer with true autocomplete search.

    The searchbox is a small Streamlit fragment: typing only reruns this market
    explorer fragment, not the whole dashboard or the live chart page.
    """
    st.markdown("## 📈 Markets")
    st.caption(
        "Stocks, NSE/BSE futures, NSE/BSE options and MCX contracts use the same "
        "browser-live Lightweight Charts workspace. Type a symbol to get live "
        "Upstox suggestions."
    )

    if st_searchbox is None:
        # Safe fallback for environments that have not installed the optional
        # autocomplete component yet.
        tabs=st.tabs(["Stocks","Futures","Options","MCX"])
        with tabs[0]:
            q=st.text_input(
                "Stock symbol", value="RELIANCE", key="market_stock_query",
                help="Type a symbol such as RELIANCE, HDFCBANK, INFY or TCS."
            )
            rows=search_market_instruments(token,q,"NSE,BSE","EQ","EQ")
            if rows:
                labels=[_market_result_label(r) for r in rows]
                idx=st.selectbox(
                    "Suggestions",range(len(rows)),
                    format_func=lambda i:labels[i],key="market_stock_pick"
                )
                render_generic_market_chart(token,rows[idx],5)
            else:
                st.info("No equity matched that search.")
        with tabs[1]:
            q=st.text_input(
                "Future search", value="NIFTY", key="market_future_query",
                help="Examples: NIFTY, BANKNIFTY, RELIANCE"
            )
            rows=search_market_instruments(token,q,"NSE,BSE","FO","FUT","current_month")
            if rows:
                labels=[_market_result_label(r) for r in rows]
                idx=st.selectbox(
                    "Suggestions",range(len(rows)),
                    format_func=lambda i:labels[i],key="market_future_pick"
                )
                render_generic_market_chart(token,rows[idx],5)
            else:
                st.info("No current-month NSE/BSE future matched that search.")
        with tabs[2]:
            q=st.text_input(
                "Option search", value="NIFTY", key="market_option_query",
                help="Examples: NIFTY, BANKNIFTY, RELIANCE, HDFCBANK"
            )
            rows=search_market_instruments(token,q,"NSE,BSE","FO","CE,PE","current_month")
            if rows:
                labels=[_market_result_label(r) for r in rows]
                idx=st.selectbox(
                    "Suggestions",range(len(rows)),
                    format_func=lambda i:labels[i],key="market_option_pick"
                )
                render_generic_market_chart(token,rows[idx],5)
            else:
                st.info("No current-month option matched that search.")
        with tabs[3]:
            q=st.text_input(
                "MCX contract search", value="CRUDEOIL", key="market_mcx_query",
                help="Examples: CRUDEOIL, GOLD, SILVER, NATURALGAS"
            )
            rows=search_market_instruments(token,q,"MCX","FO","FUT","current_month")
            if rows:
                labels=[_market_result_label(r) for r in rows]
                idx=st.selectbox(
                    "Suggestions",range(len(rows)),
                    format_func=lambda i:labels[i],key="market_mcx_pick"
                )
                render_generic_market_chart(token,rows[idx],5,title_prefix="MCX • ")
            else:
                st.info("No current-month MCX future matched that search.")
        return

    # Keep autocomplete reruns isolated to this fragment. This is deliberately
    # NOT a timer/refresh loop; the live chart websocket continues independently.
    @st.fragment
    def _market_autocomplete_fragment():
        tabs=st.tabs(["Stocks","Futures","Options","MCX"])

        def box(label, key, default_searchterm, placeholder, search_args, title_prefix=""):
            exchanges, segments, instrument_types, expiry = search_args

            def _search(searchterm):
                term=str(searchterm or "").strip()
                if not term:
                    return []
                rows=search_market_instruments(
                    token, term, exchanges, segments, instrument_types, expiry
                )
                return [(_market_result_label(r), r) for r in rows[:30]]

            selected=st_searchbox(
                _search,
                key=key,
                label=label,
                placeholder=placeholder,
                default_searchterm=default_searchterm,
                default_use_searchterm=False,
                debounce=180,
                rerun_on_update=True,
                rerun_scope="fragment",
                edit_after_submit="option",
                clear_on_submit=False,
            )

            # Show the default contract on first load, but once the user starts
            # typing, the selected tuple returned by the component takes over.
            if isinstance(selected, dict):
                row=selected
                st.session_state[key + "_selected_row"]=row
            else:
                row=st.session_state.get(key + "_selected_row")

            if row is None:
                initial=_search(default_searchterm)
                if initial:
                    row=initial[0][1]
                    st.session_state[key + "_selected_row"]=row

            if row:
                render_generic_market_chart(token,row,5,title_prefix=title_prefix)
            else:
                st.info("Start typing to see Upstox instrument suggestions.")

        with tabs[0]:
            box(
                "Search stocks",
                "market_stock_autocomplete",
                "RELIANCE",
                "Type RELIANCE, INFY, TCS, HDFCBANK…",
                ("NSE,BSE","EQ","EQ",""),
            )
        with tabs[1]:
            box(
                "Search futures",
                "market_future_autocomplete",
                "NIFTY",
                "Type NIFTY, BANKNIFTY, RELIANCE…",
                ("NSE,BSE","FO","FUT","current_month"),
            )
        with tabs[2]:
            box(
                "Search options",
                "market_option_autocomplete",
                "NIFTY",
                "Type NIFTY, BANKNIFTY, RELIANCE…",
                ("NSE,BSE","FO","CE,PE","current_month"),
            )
        with tabs[3]:
            box(
                "Search MCX",
                "market_mcx_autocomplete",
                "CRUDEOIL",
                "Type CRUDEOIL, GOLD, SILVER, NATURALGAS…",
                ("MCX","FO","FUT","current_month"),
                title_prefix="MCX • ",
            )

    _market_autocomplete_fragment()


def main():
    inject_trader_css()
    token=token_from_secrets()
    with st.sidebar:
        st.header("⚡ OI Pulse Pro")
        if not token:
            token=st.text_input("Upstox access token",type="password")
        st.caption("Live market data • Upstox V3")

    if not token:
        st.info("Add UPSTOX_ACCESS_TOKEN to Streamlit Secrets."); return
    maybe_archive_after_close(token)

    # Build the live index universe from Upstox's BOD files. If the public files are
    # temporarily unavailable, the guaranteed NIFTY/BANK fallback remains usable.
    catalog, catalog_errors = load_upstox_index_catalog()
    if catalog:
        register_index_configs(catalog)

    st.title("⚡ OI Pulse Pro")
    st.caption("Trader-first index terminal • live OI battlefield • levels • futures • regime • index drivers • research")

    names=index_display_groups()
    default_name=st.session_state.get("selected_index","NIFTY 50")
    if default_name not in names:
        default_name=names[0]
    selected=st.selectbox("📌 Select index", names, index=names.index(default_name), key="selected_index",
                          help="The list is populated from Upstox's NSE/BSE index instrument universe. Derivatives-enabled indices get the full OI terminal; others get index-only analytics.")
    cfg=INDEXES[selected]

    # IMPORTANT: mount the browser chart outside the analytics fragment.
    # The fragment may rerun every few seconds, but this iframe stays alive and
    # receives one-second ticks through Supabase Realtime.
    _chart_tf = st.radio(
        "Chart timeframe",
        ["1m","3m","5m","15m","30m","1H"],
        index=2,
        horizontal=True,
        key=f"static_chart_tf_{selected.replace(' ','_')}",
    )
    _chart_tf_minutes={"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1H":60}[_chart_tf]
    render_static_live_chart(token, selected, _chart_tf_minutes)

    c1,c2,c3=st.columns([1.25,1.25,1])
    c1.metric("Selected index", selected)
    c2.metric("Coverage", "PRIMARY OI" if selected in ("NIFTY 50","BANK NIFTY") else "AUTO-DETECT")
    c3.metric("Universe", f"{len(names)} indices")
    if catalog_errors and not catalog:
        st.caption("Index universe refresh temporarily unavailable; using the guaranteed NIFTY/BANK list. Use the sidebar search to find a specific index.")

    # IMPORTANT: there is deliberately NO st.fragment(run_every=...) here.
    # The old fragment caused Streamlit to rebuild page elements every few seconds.
    # Live prices are transported by the process-lifetime Upstox V3 websocket ->
    # Supabase Realtime -> Lightweight Charts update(), so the browser chart moves
    # without a Streamlit rerun.
    render_cross_index(token)
    render_index_v3(selected,token,include_chart=False)
    st.markdown("---")
    render_market_explorer(token)
    st.markdown("---")
    tabs=st.tabs(["SIGNAL VALIDATION","FEATURE LAB"])
    with tabs[0]: validation_panel()
    with tabs[1]: feature_gate_panel()

if __name__=="__main__": main()
