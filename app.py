
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import app as core

IST = ZoneInfo("Asia/Kolkata")

# The old analytics engine is intentionally kept in legacy_app.py so none of the
# existing market-data/option-chain logic is lost. This entrypoint only changes
# the presentation/runtime model: no fragment refresh, no analytics pulse control,
# no event-risk UI, no risk-budget UI. The browser owns live chart updates.

st.markdown("""
<style>
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--card:#fff;--bg:#f6f8fb}
.stApp{background:var(--bg)}
.block-container{max-width:1540px;padding-top:1rem;padding-bottom:3rem}
h1,h2,h3{color:var(--ink);letter-spacing:-.025em}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:0 5px 20px rgba(15,23,42,.045)}
.small{font-size:11px;color:var(--muted)}
.market-tabs{margin-top:4px}
.section{margin:20px 0 8px}
</style>
""", unsafe_allow_html=True)


def token_from_secrets_or_sidebar():
    try:
        secret = str(st.secrets.get("UPSTOX_ACCESS_TOKEN", "")).strip()
    except Exception:
        secret = ""
    with st.sidebar:
        st.markdown("## ⚡ OI Pulse Pro")
        token = secret or st.text_input("Upstox access token", type="password")
        if token:
            st.caption("Live Upstox V3 stream • browser chart updates independently")
        else:
            st.caption("Enter the Upstox access token to start the terminal.")
    return token


def supabase_cfg():
    return core._supabase_config()


@st.cache_resource(show_spinner=False)
def live_bridge(token, mapping_tuple):
    """
    One process-level V3 stream. It publishes a maximum of one tick/sec/instrument
    to Supabase live_ticks. The iframe then consumes those rows without a Streamlit
    rerun. This is the key fix for the frozen chart.
    """
    url, key = supabase_cfg()
    for symbol, instrument_key in mapping_tuple:
        core.INDEXES.setdefault(symbol, {
            "key": instrument_key,
            "step": 0,
            "strike_window": 14,
            "exchange": instrument_key.split("_")[0],
            "trading_symbol": symbol,
        })
    feed = core.LiveFeedCache(token, url, key)
    feed.start([k for _, k in mapping_tuple])
    return feed


def start_live_stream(token, mappings):
    clean = tuple(sorted({(str(s), str(k)) for s, k in mappings if k}))
    if not clean:
        return None
    return live_bridge(token, clean)


def search_instrument(token, query, exchanges="NSE", segments="EQ", instrument_types="", expiry=""):
    try:
        params = {
            "query": str(query)[:50],
            "exchanges": exchanges,
            "segments": segments,
            "page_number": 1,
            "records": 30,
        }
        if instrument_types:
            params["instrument_types"] = instrument_types
        if expiry:
            params["expiry"] = expiry
        d = core.api_get("/instruments/search", token, params)
        rows = d.get("data", []) if isinstance(d, dict) else []
        return [x for x in rows if isinstance(x, dict) and x.get("instrument_key")]
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def search_instrument_cached(token, query, exchanges, segments, instrument_types, expiry):
    return search_instrument(token, query, exchanges, segments, instrument_types, expiry)


def live_ticker(symbols):
    url, key = supabase_cfg()
    if not url or not key:
        return
    safe_symbols = [str(x) for x in symbols if x]
    payload = json.dumps(safe_symbols)
    html = f"""
<!doctype html><html><head><meta charset="utf-8">
<style>
*{{box-sizing:border-box}}body{{margin:0;background:transparent;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:#0f172a}}
.grid{{display:grid;grid-template-columns:repeat({max(1,min(4,len(safe_symbols)))},1fr);gap:10px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:12px 14px;min-height:82px;box-shadow:0 4px 16px rgba(15,23,42,.04)}}
.name{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;font-weight:800}}
.price{{font-size:24px;font-weight:850;margin-top:3px;line-height:1.1}}
.move{{font-size:11px;margin-top:4px;font-weight:750}}
.up{{color:#078447}}.down{{color:#d12f3d}}.flat{{color:#64748b}}
.dot{{display:inline-block;width:7px;height:7px;border-radius:50%;background:#16a34a;margin-right:5px}}
.age{{font-size:9px;color:#94a3b8;float:right;font-weight:600}}
@media(max-width:850px){{.grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<div class="grid" id="grid"></div>
<script>
const URL={json.dumps(url)}, KEY={json.dumps(key)}, SYMBOLS={payload};
const root=document.getElementById('grid');
const state={{}};
function esc(x){{return String(x).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
function render(){{
  root.innerHTML=SYMBOLS.map(s=>{{
    const x=state[s]||{{}};
    const p=Number(x.price||0), cp=Number(x.previous_close||0);
    const m=cp?p/cp*100-100:0, cls=m>0.001?'up':m<-0.001?'down':'flat';
    const age=x.ts?Math.max(0,Math.round((Date.now()-new Date(x.ts).getTime())/1000)):null;
    return `<div class="card"><div class="name"><span class="dot"></span>${{esc(s)}} <span class="age">${{age===null?'waiting':age+'s'}}</span></div>
      <div class="price">${{p?p.toLocaleString('en-IN',{{minimumFractionDigits:2,maximumFractionDigits:2}}):'—'}}</div>
      <div class="move ${{cls}}">${{cp?(m>=0?'▲ +':'▼ ')+m.toFixed(2)+'%':'Live tick stream waiting'}}</div></div>`;
  }}).join('');
}}
async function pull(){{
  if(!URL||!KEY) return;
  try{{
    const q=SYMBOLS.map(s=>'symbol=eq.'+encodeURIComponent(s)).join('&');
    const r=await fetch(URL+'/rest/v1/live_ticks?'+q+'&select=symbol,ts,price,previous_close&order=ts.desc&limit='+Math.max(10,SYMBOLS.length*4),
      {{headers:{{apikey:KEY,Authorization:'Bearer '+KEY}},cache:'no-store'}});
    if(!r.ok) return;
    const rows=await r.json();
    for(const row of rows){{
      if(!state[row.symbol]) state[row.symbol]=row;
      else if(new Date(row.ts)>new Date(state[row.symbol].ts)) state[row.symbol]=row;
    }}
    render();
  }}catch(e){{}}
}}
async function start(){{
  render(); await pull();
  setInterval(pull,1000);
  try{{
    const sb=window.supabase?.createClient(URL,KEY);
    if(sb){{
      const ch=sb.channel('terminal-live-ticker')
        .on('postgres_changes',{{event:'INSERT',schema:'public',table:'live_ticks'}},
          p=>{{if(p.new&&SYMBOLS.includes(p.new.symbol)){{state[p.new.symbol]=p.new;render();}}}})
        .subscribe();
    }}
  }}catch(e){{}}
}}
start();
</script></body></html>
"""
    components.html(html, height=105, scrolling=False)


def render_live_chart(token, symbol, key, tf_label="5m", levels=None, spot=0.0):
    tf = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1H": 60}[tf_label]
    core.INDEXES.setdefault(symbol, {
        "key": key, "step": 0, "strike_window": 14,
        "exchange": key.split("_")[0], "trading_symbol": symbol,
    })
    start_live_stream(token, [(symbol, key)])
    candles = core.upstox_intraday_candles_df(token, key, tf)
    # The chart is mounted exactly once in this Streamlit run. There is no
    # @st.fragment around it and no timer that rebuilds the iframe.
    core.render_upstox_tv_chart(candles, spot, levels or {"support": [], "resistance": []}, symbol, tf, token)
    st.caption("🟢 Live chart — candles are updated in the browser with Lightweight Charts 5.2 + Supabase live ticks. Streamlit does not refresh the chart.")


def initial_quote(token, key):
    try:
        px, cp = core.underlying_ltp(token, key)
        return float(px), float(cp)
    except Exception:
        return 0.0, 0.0


def render_overview(token):
    nkey = core.INDEXES["NIFTY 50"]["key"]
    bkey = core.INDEXES["BANK NIFTY"]["key"]
    start_live_stream(token, [("NIFTY 50", nkey), ("BANK NIFTY", bkey)])
    live_ticker(["NIFTY 50", "BANK NIFTY"])

    npx, ncp = initial_quote(token, nkey)
    bpx, bcp = initial_quote(token, bkey)
    nmove = (npx / ncp - 1) * 100 if ncp else 0
    bmove = (bpx / bcp - 1) * 100 if bcp else 0
    rel = bmove - nmove

    st.markdown("## NIFTY vs BANK NIFTY")
    c1, c2, c3 = st.columns(3)
    c1.metric("NIFTY 50", f"{npx:,.2f}", f"{nmove:+.2f}%")
    c2.metric("BANK NIFTY", f"{bpx:,.2f}", f"{bmove:+.2f}%")
    c3.metric("Relative", f"{rel:+.2f}%")
    st.caption("The cards above are browser-live. The numbers shown by Streamlit are the initial snapshot only; the live ticker is the continuously updating layer.")

    tf = st.radio("Chart timeframe", ["1m", "3m", "5m", "15m", "30m", "1H"], index=2, horizontal=True)
    render_live_chart(token, "NIFTY 50", nkey, tf, spot=npx)


def render_index(token, name):
    cfg = core.INDEXES[name]
    key = cfg["key"]
    start_live_stream(token, [(name, key), ("NIFTY 50", core.INDEXES["NIFTY 50"]["key"]), ("BANK NIFTY", core.INDEXES["BANK NIFTY"]["key"])])
    live_ticker(["NIFTY 50", "BANK NIFTY", name] if name not in ("NIFTY 50", "BANK NIFTY") else ["NIFTY 50", "BANK NIFTY"])

    px, cp = initial_quote(token, key)
    move = (px / cp - 1) * 100 if cp else 0
    st.markdown(f"## {name}")
    a, b, c = st.columns(3)
    a.metric("Spot", f"{px:,.2f}", f"{move:+.2f}%")
    try:
        market = core.session_market_metrics(token, key)
        b.metric("VWAP", f"{market.get('vwap', 0):,.2f}" if market.get("vwap") else "—")
        c.metric("5m", f"{market.get('ret5', 0):+.2f}%")
    except Exception:
        b.metric("VWAP", "—")
        c.metric("5m", "—")

    chart_levels = None
    chart_df = None
    chart_expiry = None
    step = cfg.get("step", 50 if name == "NIFTY 50" else 100)
    if name in ("NIFTY 50", "BANK NIFTY"):
        try:
            contracts = core.option_contracts(token, key)
            chart_expiry = core.nearest_expiry(contracts)
            if chart_expiry:
                chain = core.option_chain(token, key, chart_expiry)
                chart_df = core.build_option_df(chain)
                if not chart_df.empty:
                    chart_df["ce_doi_tick"] = 0.0
                    chart_df["pe_doi_tick"] = 0.0
                    chart_df = core.enrich_advanced(chart_df, px, step, name)
                    chart_levels = core.calculate_levels(chart_df, px, step)
        except Exception:
            chart_df = None

    tf = st.radio("Chart timeframe", ["1m", "3m", "5m", "15m", "30m", "1H"], index=2, horizontal=True, key=f"tf_{name}")
    render_live_chart(token, name, key, tf, chart_levels, px)

    # Keep the strongest existing OI features, but do not render the old risk/event
    # sections or the old analytics-pulse controls.
    if chart_df is not None and not chart_df.empty and chart_levels:
        st.markdown("## ⚔️ OI battlefield")
        core.trader_oi_battlefield(chart_df, px, step, chart_levels)
        with st.expander("Full option chain", expanded=False):
            core.option_chain_display(chart_df, px, step)
            core.option_chain_download(chart_df, name, chart_expiry)

        try:
            fut = core.futures_context(token, name, px)
            st.markdown("## Futures")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Futures", f"{fut.get('ltp', 0):,.2f}" if fut.get("available") else "—")
            f2.metric("Basis", f"{fut.get('basis', 0):+.2f}" if fut.get("available") else "—")
            f3.metric("OI", core.format_oi(fut.get("oi", 0)) if fut.get("available") else "—")
            f4.metric("ΔOI", core.sign_text(fut.get("doi", 0)) if fut.get("available") else "—")
        except Exception:
            pass

        try:
            fut = core.futures_context(token, name, px)
            st.markdown("## Futures")
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Futures", f"{fut.get('ltp', 0):,.2f}" if fut.get("available") else "—")
            f2.metric("Basis", f"{fut.get('basis', 0):+.2f}" if fut.get("available") else "—")
            f3.metric("OI", core.format_oi(fut.get("oi", 0)) if fut.get("available") else "—")
            f4.metric("ΔOI", core.sign_text(fut.get("doi", 0)) if fut.get("available") else "—")
        except Exception:
            pass


def render_stock(token):
    st.markdown("## Stocks")
    query = st.text_input("Search NSE/BSE stock", value="RELIANCE", key="stock_query")
    rows = search_instrument_cached(token, query, "NSE,BSE", "EQ", "", "")
    if not rows:
        st.info("No stock instrument found.")
        return
    choices = [f"{r.get('name') or r.get('trading_symbol')} · {r.get('exchange')} · {r.get('instrument_key')}" for r in rows]
    selected = st.selectbox("Instrument", choices, key="stock_select")
    row = rows[choices.index(selected)]
    name = str(row.get("trading_symbol") or row.get("name") or query).strip()
    key = row["instrument_key"]

    start_live_stream(token, [(name, key)])
    live_ticker([name])
    px, cp = initial_quote(token, key)
    move = (px / cp - 1) * 100 if cp else 0
    a, b, c = st.columns(3)
    a.metric(name, f"{px:,.2f}", f"{move:+.2f}%")
    b.metric("Exchange", row.get("exchange", "—"))
    c.metric("ISIN", row.get("isin", "—") or "—")
    tf = st.radio("Chart timeframe", ["1m", "5m", "15m", "30m", "1H"], index=1, horizontal=True, key="stock_tf")
    render_live_chart(token, name, key, tf)


def render_futures(token):
    st.markdown("## Futures")
    q = st.text_input("Future underlying", value="NIFTY", key="future_query")
    rows = search_instrument_cached(token, q, "NSE,BSE,MCX", "FUT,FO", "FUT", "current_month")
    if not rows:
        st.info("No current-month future found for that query.")
        return
    rows = sorted(rows, key=lambda x: str(x.get("expiry", "9999-99-99")))
    choices = [f"{r.get('trading_symbol') or r.get('name')} · {r.get('exchange')} · {r.get('expiry')} · {r.get('instrument_key')}" for r in rows]
    selected = st.selectbox("Contract", choices, key="future_select")
    row = rows[choices.index(selected)]
    name = str(row.get("trading_symbol") or row.get("name"))
    key = row["instrument_key"]

    start_live_stream(token, [(name, key)])
    live_ticker([name])
    px, cp = initial_quote(token, key)
    move = (px / cp - 1) * 100 if cp else 0
    a, b, c, d = st.columns(4)
    a.metric("LTP", f"{px:,.2f}", f"{move:+.2f}%")
    b.metric("Expiry", str(row.get("expiry", "—")))
    c.metric("Lot size", str(row.get("lot_size", "—")))
    d.metric("Tick size", str(row.get("tick_size", "—")))
    tf = st.radio("Chart timeframe", ["1m", "5m", "15m", "30m", "1H"], index=1, horizontal=True, key="future_tf")
    render_live_chart(token, name, key, tf)


def render_mcx(token):
    st.markdown("## MCX")
    q = st.text_input("MCX contract search", value="GOLD", key="mcx_query")
    rows = search_instrument_cached(token, q, "MCX", "FO,COMM,FUT", "FUT", "current_month")
    if not rows:
        # Some Upstox catalogues classify commodities differently; broaden once.
        rows = search_instrument_cached(token, q, "MCX", "FO,COMM,FUT", "", "current_month")
    if not rows:
        st.info("No MCX contract found for that query.")
        return
    rows = sorted(rows, key=lambda x: str(x.get("expiry", "9999-99-99")))
    choices = [f"{r.get('trading_symbol') or r.get('name')} · {r.get('expiry')} · {r.get('instrument_key')}" for r in rows]
    selected = st.selectbox("MCX contract", choices, key="mcx_select")
    row = rows[choices.index(selected)]
    name = str(row.get("trading_symbol") or row.get("name"))
    key = row["instrument_key"]

    start_live_stream(token, [(name, key)])
    live_ticker([name])
    px, cp = initial_quote(token, key)
    move = (px / cp - 1) * 100 if cp else 0
    a, b, c = st.columns(3)
    a.metric("LTP", f"{px:,.2f}", f"{move:+.2f}%")
    b.metric("Expiry", str(row.get("expiry", "—")))
    c.metric("Lot size", str(row.get("lot_size", "—")))
    tf = st.radio("Chart timeframe", ["1m", "5m", "15m", "30m", "1H"], index=1, horizontal=True, key="mcx_tf")
    render_live_chart(token, name, key, tf)


def render_options(token):
    st.markdown("## Options")
    underlying = st.selectbox("Underlying", ["NIFTY 50", "BANK NIFTY"], key="opt_underlying")
    cfg = core.INDEXES[underlying]
    contracts = core.option_contracts(token, cfg["key"])
    expiry = core.nearest_expiry(contracts)
    if not expiry:
        st.info("No active option expiry returned by Upstox.")
        return
    chain = core.option_chain(token, cfg["key"], expiry)
    df = core.build_option_df(chain)
    if df.empty:
        st.info("Option chain is empty.")
        return

    spot, _ = initial_quote(token, cfg["key"])
    step = cfg["step"]
    df["distance"] = (df["strike"] - spot).abs()
    atm = df.loc[df["distance"].idxmin()]
    st.caption(f"Expiry {expiry} • ATM {atm['strike']:,.0f} • Spot {spot:,.2f}")

    # Subscribe to ATM CE/PE so their LTPs can be used in the browser-live mini cards.
    maps = []
    for k, label in [(atm.get("ce_key"), f"{underlying} ATM CE"), (atm.get("pe_key"), f"{underlying} ATM PE")]:
        if k:
            maps.append((label, k))
    start_live_stream(token, maps)
    live_ticker([x[0] for x in maps])

    o1, o2 = st.columns(2)
    with o1:
        st.metric("ATM CE", f"₹{float(atm.get('ce_ltp', 0)):,.2f}")
    with o2:
        st.metric("ATM PE", f"₹{float(atm.get('pe_ltp', 0)):,.2f}")

    try:
        heat_df = core.enrich_advanced(df.assign(ce_doi_tick=0.0, pe_doi_tick=0.0), spot, step, underlying)
        levels = core.calculate_levels(heat_df, spot, step)
    except Exception:
        levels = None
    if levels:
        st.markdown("### OI heatmap")
        core.oi_heatmap(df, spot, step, levels)

    with st.expander("Full option chain", expanded=True):
        core.option_chain_display(df, spot, step)
        core.option_chain_download(df, underlying, expiry)


def render_archive(token):
    st.markdown("## Today's market archive")
    st.caption("Upstox V3 exposes the current trading day's intraday candles. This saves the full returned 1-minute series to Supabase price_candles using symbol+timestamp idempotency.")
    if st.button("Save today's NIFTY + BANK NIFTY 1-minute data to Supabase", type="primary"):
        result = core.archive_today_prices(token, ["NIFTY 50", "BANK NIFTY"])
        st.success(f"Saved {result.get('rows', 0)} candle rows." if result.get("saved") else f"Archive not saved: {result.get('reason', 'no rows')}")
    url, key = supabase_cfg()
    if not url or not key:
        st.warning("Supabase credentials are not configured in Streamlit Secrets, so browser live ticks and the archive cannot persist.")
    else:
        st.success("Supabase persistence is configured. The live bridge writes one tick/second/instrument and the archive is idempotent.")


def main():
    token = token_from_secrets_or_sidebar()
    if not token:
        st.info("Enter your Upstox access token in the sidebar.")
        return

    if supabase_cfg()[0] and supabase_cfg()[1]:
        start_archive_worker(token)

    st.title("⚡ OI Pulse Pro")
    st.caption("Live trading terminal • Upstox V3 • Lightweight Charts 5.2 • no Streamlit refresh loop")

    market = st.radio(
        "Market",
        ["NIFTY / BANK", "OPTIONS", "FUTURES", "MCX", "STOCKS", "TODAY'S DATA"],
        horizontal=True,
        key="market_section",
    )
    if market == "NIFTY / BANK":
        choices = ["NIFTY 50", "BANK NIFTY"]
        selected = st.selectbox("Instrument", choices, key="main_index")
        if selected == "NIFTY 50":
            render_overview(token)
        else:
            render_index(token, selected)
    elif market == "OPTIONS":
        render_options(token)
    elif market == "FUTURES":
        render_futures(token)
    elif market == "MCX":
        render_mcx(token)
    elif market == "STOCKS":
        render_stock(token)
    else:
        render_archive(token)


if __name__ == "__main__":
    main()
