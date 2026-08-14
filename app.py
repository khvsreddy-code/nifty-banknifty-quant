
import math, time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Nifty Quant Pulse", page_icon="⚡", layout="wide")

IST = ZoneInfo("Asia/Kolkata")
V2 = "https://api.upstox.com/v2"
V3 = "https://api.upstox.com/v3"

INDEXES = {
    "NIFTY 50": {
        "key": "NSE_INDEX|Nifty 50",
        "step": 50,
        "ref_weights": {
            # Reference weights from NSE Indices May 29 2026 factsheet.
            "HDFCBANK": 10.56, "ICICIBANK": 8.32, "RELIANCE": 8.27,
            "BHARTIARTL": 5.20, "LT": 4.43, "INFY": 3.77,
            "SBIN": 3.71, "AXISBANK": 3.42, "KOTAKBANK": 2.62,
            "ITC": 2.56,
        },
    },
    "BANK NIFTY": {
        "key": "NSE_INDEX|Nifty Bank",
        "step": 100,
        "ref_weights": {
            # Reference weights from NSE Indices Apr 30 2026 factsheet.
            "HDFCBANK": 18.37, "ICICIBANK": 13.55, "AXISBANK": 10.02,
            "SBIN": 9.93, "KOTAKBANK": 9.67, "FEDERALBNK": 6.27,
            "INDUSINDBK": 5.35, "AUBANK": 4.97, "BANKBARODA": 4.34,
            "IDFCFIRSTB": 4.12,
        },
    },
}

def token_from_secrets():
    try:
        return str(st.secrets.get("UPSTOX_ACCESS_TOKEN", "")).strip()
    except Exception:
        return ""

def headers(token):
    return {"Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"}

def get(url, token, params=None, timeout=20):
    r=requests.get(url, headers=headers(token), params=params, timeout=timeout)
    if not r.ok:
        try: body=r.json()
        except Exception: body=r.text[:500]
        raise RuntimeError(f"Upstox HTTP {r.status_code}: {body}")
    return r.json()

@st.cache_data(ttl=21600, show_spinner=False)
def resolve_symbol(token, symbol):
    # Instrument Search is V2 per current Upstox documentation.
    d=get(f"{V2}/instruments/search", token, {
        "query":symbol, "exchanges":"NSE", "segments":"EQ",
        "instrument_types":"EQ", "page_number":1, "records":20
    })
    rows=d.get("data",[]) or []
    exact=[x for x in rows if x.get("exchange")=="NSE"
           and x.get("segment")=="NSE_EQ"
           and x.get("instrument_type")=="EQ"
           and str(x.get("trading_symbol","")).upper()==symbol.upper()]
    return exact[0] if exact else next(
        (x for x in rows if x.get("exchange")=="NSE"
         and x.get("segment")=="NSE_EQ"
         and x.get("instrument_type")=="EQ"), None)

@st.cache_data(ttl=4, show_spinner=False)
def ltp_quotes(token, keys):
    if not keys: return {}
    out={}
    for i in range(0,len(keys),500):
        d=get(f"{V3}/market-quote/ltp", token, {"instrument_key":",".join(keys[i:i+500])})
        out.update(d.get("data",{}) or {})
    return out

@st.cache_data(ttl=4, show_spinner=False)
def option_chain(token, index_key):
    d=get(f"{V2}/option/chain", token, {
        "instrument_key":index_key, "expiry_date":"current_week"
    })
    data=d.get("data",[]) if isinstance(d,dict) else []
    return data if isinstance(data,(list,dict)) else []

@st.cache_data(ttl=21600, show_spinner=False)
def historical_5m(token, index_key):
    # Use current day intraday candles where available. The exact endpoint
    # is V3 historical candle; fallback is handled by caller.
    now=datetime.now(IST)
    today=now.date().isoformat()
    url=f"{V3}/historical-candle/intraday/{index_key}/minutes/5"
    try:
        d=get(url,token)
        candles=(d.get("data",{}) or {}).get("candles",[]) or []
        if not candles: return pd.DataFrame()
        df=pd.DataFrame(candles,columns=["ts","open","high","low","close","volume","oi"])
        for c in ["open","high","low","close","volume","oi"]:
            df[c]=pd.to_numeric(df[c],errors="coerce")
        df["ts"]=pd.to_datetime(df["ts"],errors="coerce")
        return df.sort_values("ts")
    except Exception:
        return pd.DataFrame()

def load_weights(index_name, uploaded):
    if uploaded is not None:
        x=pd.read_csv(uploaded)
        cols={c.lower().strip():c for c in x.columns}
        if "symbol" not in cols or "weight_pct" not in cols:
            raise ValueError("CSV needs symbol, weight_pct")
        x=x.rename(columns={cols["symbol"]:"symbol",cols["weight_pct"]:"weight_pct"})
        x=x[["symbol","weight_pct"]].copy()
        x["symbol"]=x.symbol.astype(str).str.upper().str.strip()
        x["weight_pct"]=pd.to_numeric(x.weight_pct,errors="coerce")
        x=x.dropna().query("weight_pct>0")
        return x.sort_values("weight_pct",ascending=False), True
    ref=INDEXES[index_name]["ref_weights"]
    return pd.DataFrame({"symbol":list(ref),"weight_pct":list(ref.values())}), False

def zscore01(s):
    s=pd.Series(s,dtype=float).fillna(0)
    if len(s)==0: return s
    lo,hi=float(s.min()),float(s.max())
    if hi-lo<1e-12: return pd.Series(np.full(len(s),0.5),index=s.index)
    return (s-lo)/(hi-lo)

def build_option_df(chain):
    """Normalize Upstox option-chain rows defensively.

    Upstox documents /v2/option/chain as a list of rows containing
    strike_price, call_options and put_options.  During market transitions
    an API response can still be empty/partial, so this function always
    returns a DataFrame with the expected columns instead of raising a
    KeyError.
    """
    columns = [
        "strike","ce_ltp","ce_oi","ce_prev_oi","ce_vol","ce_close","ce_iv",
        "pe_ltp","pe_oi","pe_prev_oi","pe_vol","pe_close","pe_iv",
        "ce_doi","pe_doi","ce_prem_chg","pe_prem_chg"
    ]

    if chain is None:
        return pd.DataFrame(columns=columns)

    # Normally `data` is a list. Be tolerant of wrappers/dicts returned by
    # proxies or SDKs.
    if isinstance(chain, dict):
        if isinstance(chain.get("data"), list):
            chain = chain["data"]
        elif isinstance(chain.get("data"), dict):
            chain = list(chain["data"].values())
        else:
            chain = list(chain.values())

    if not isinstance(chain, (list, tuple)):
        return pd.DataFrame(columns=columns)

    def num(value, default=0.0):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    rows = []
    for x in chain:
        if not isinstance(x, dict):
            continue

        # Official response key is strike_price.
        strike_raw = x.get("strike_price")
        if strike_raw is None:
            # Defensive aliases for SDK/proxy transformations.
            strike_raw = x.get("strike") or x.get("strikePrice")
        try:
            strike = float(strike_raw)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(strike):
            continue

        c = x.get("call_options") or x.get("callOptions") or {}
        p = x.get("put_options") or x.get("putOptions") or {}
        if not isinstance(c, dict): c = {}
        if not isinstance(p, dict): p = {}

        cm = c.get("market_data") or c.get("marketData") or {}
        pm = p.get("market_data") or p.get("marketData") or {}
        cg = c.get("option_greeks") or c.get("optionGreeks") or {}
        pg = p.get("option_greeks") or p.get("optionGreeks") or {}
        if not isinstance(cm, dict): cm = {}
        if not isinstance(pm, dict): pm = {}
        if not isinstance(cg, dict): cg = {}
        if not isinstance(pg, dict): pg = {}

        ce_ltp = num(cm.get("ltp"))
        pe_ltp = num(pm.get("ltp"))
        ce_close = num(cm.get("close_price") if cm.get("close_price") is not None
                       else cm.get("closePrice"))
        pe_close = num(pm.get("close_price") if pm.get("close_price") is not None
                       else pm.get("closePrice"))
        ce_oi = num(cm.get("oi"))
        pe_oi = num(pm.get("oi"))
        ce_prev_oi = num(cm.get("prev_oi") if cm.get("prev_oi") is not None
                         else cm.get("prevOi"))
        pe_prev_oi = num(pm.get("prev_oi") if pm.get("prev_oi") is not None
                         else pm.get("prevOi"))

        rows.append({
            "strike": strike,
            "ce_ltp": ce_ltp, "ce_oi": ce_oi, "ce_prev_oi": ce_prev_oi,
            "ce_vol": num(cm.get("volume")), "ce_close": ce_close,
            "ce_iv": num(cg.get("iv")),
            "pe_ltp": pe_ltp, "pe_oi": pe_oi, "pe_prev_oi": pe_prev_oi,
            "pe_vol": num(pm.get("volume")), "pe_close": pe_close,
            "pe_iv": num(pg.get("iv")),
            "ce_doi": ce_oi - ce_prev_oi,
            "pe_doi": pe_oi - pe_prev_oi,
            "ce_prem_chg": ((ce_ltp / ce_close) - 1) * 100
                            if ce_close > 0 else 0.0,
            "pe_prem_chg": ((pe_ltp / pe_close) - 1) * 100
                            if pe_close > 0 else 0.0,
        })

    if not rows:
        return pd.DataFrame(columns=columns)

    return (
        pd.DataFrame(rows, columns=columns)
        .dropna(subset=["strike"])
        .sort_values("strike")
        .drop_duplicates(subset=["strike"], keep="last")
        .reset_index(drop=True)
    )

def level_engine(df, spot, step):
    if df is None or df.empty or not np.isfinite(float(spot)):
        return {}, pd.DataFrame()
    required = ["strike","ce_oi","pe_oi","ce_doi","pe_doi","ce_prem_chg","pe_prem_chg"]
    if any(c not in df.columns for c in required):
        return {}, pd.DataFrame()
    df=df.copy()
    df["dist"]=abs(df.strike-spot)/max(spot,1)
    # Only strikes near spot are relevant for intraday reaction levels.
    window=max(10*step, spot*0.025)
    d=df[df["dist"]<=window/spot].copy()
    if d.empty: d=df.copy()

    # Writer evidence:
    # CE: rising OI + falling premium -> call writing / resistance.
    # PE: rising OI + falling premium -> put writing / support.
    d["ce_write"]=np.maximum(d.ce_doi,0)*np.maximum(-d.ce_prem_chg,0)
    d["pe_write"]=np.maximum(d.pe_doi,0)*np.maximum(-d.pe_prem_chg,0)

    # OI concentration is primary, fresh writing secondary.
    d["ce_oi_n"]=zscore01(np.log1p(d.ce_oi))
    d["pe_oi_n"]=zscore01(np.log1p(d.pe_oi))
    d["ce_w_n"]=zscore01(np.log1p(d.ce_write))
    d["pe_w_n"]=zscore01(np.log1p(d.pe_write))

    # Distance penalty: nearer ATM gets more relevance.
    d["near"]=np.exp(-d.dist/(0.0125))
    d["res_score"]=100*(0.55*d.ce_oi_n+0.30*d.ce_w_n+0.15*d.near)
    d["sup_score"]=100*(0.55*d.pe_oi_n+0.30*d.pe_w_n+0.15*d.near)

    # Resistance only above spot; support only below spot.
    res=d[d.strike>=spot].sort_values("res_score",ascending=False).head(5)
    sup=d[d.strike<=spot].sort_values("sup_score",ascending=False).head(5)

    # Pick top two non-adjacent zones for clean display.
    def select_levels(x, score_col):
        out=[]
        for _,r in x.iterrows():
            if all(abs(float(r.strike)-float(q.strike))>=step*0.9 for q in out):
                out.append(r)
            if len(out)>=3: break
        return out

    ress=select_levels(res,"res_score")
    sups=select_levels(sup,"sup_score")

    # Independent reversal/extension map:
    # EOR = strongest resistance zone, EOS = strongest support zone.
    # +/-1 are one strike-step beyond the core zones.
    eor=float(ress[0].strike) if ress else float(math.ceil(spot/step)*step)
    eos=float(sups[0].strike) if sups else float(math.floor(spot/step)*step)
    eor1=eor+step
    eos1=eos-step

    # Structure score: positive when support is stronger / resistance weaker.
    top_sup=float(sups[0].sup_score) if sups else 0
    top_res=float(ress[0].res_score) if ress else 0
    structure=(top_sup-top_res)/2

    # PCR by OI around ±5 strikes.
    near_df=d.iloc[(d["strike"]-spot).abs().argsort()[:11]]
    pcr=near_df.pe_oi.sum()/near_df.ce_oi.sum() if near_df.ce_oi.sum()>0 else np.nan

    return {
        "support":sups,"resistance":ress,"eos":eos,"eos1":eos1,
        "eor":eor,"eor1":eor1,"structure":structure,"pcr":pcr
    },d

def session_pressure(index_name, weights, token):
    resolved=[]
    for _,r in weights.iterrows():
        inst=resolve_symbol(token,r.symbol)
        if inst:
            resolved.append((r.symbol,float(r.weight_pct),inst["instrument_key"]))
    if not resolved: return pd.DataFrame(),0,0,0
    q=ltp_quotes(token,[x[2] for x in resolved])
    rows=[]
    for sym,w,key in resolved:
        z=q.get(key) or q.get(key.replace("|",":")) or {}
        ltp=z.get("last_price")
        cp=z.get("cp")
        if ltp is None or cp in (None,0): continue
        move=(float(ltp)/float(cp)-1)*100
        rows.append({"symbol":sym,"weight_pct":w,"ltp":float(ltp),"move_pct":move,
                     "impact_pct":w*move/100})
    df=pd.DataFrame(rows)
    if df.empty: return df,0,0,0
    return df.sort_values("impact_pct",ascending=False),float(df.impact_pct.sum()),float((df.move_pct>0).mean()*100),float(df.weight_pct.sum())

def signal_for(idx, spot, flow, breadth, level, chain_df):
    # 0..100 directional score, transparent and bounded.
    # Components:
    # stock flow 35%, breadth 20%, option structure 30%, price location 15%.
    flow_component=np.tanh(flow/0.20)*35
    breadth_component=((breadth-50)/50)*20

    structure=level.get("structure",0)
    oi_component=np.tanh(structure/30)*30

    eos,eor=level.get("eos",spot),level.get("eor",spot)
    span=max(eor-eos,1)
    loc=((spot-eos)/span-0.5)*30
    loc=max(-15,min(15,loc))
    score=flow_component+breadth_component+oi_component+loc

    if score>=35: regime="STRONG BULLISH"
    elif score>=12: regime="BULLISH"
    elif score<=-35: regime="STRONG BEARISH"
    elif score<=-12: regime="BEARISH"
    else: regime="NEUTRAL / RANGE"

    # Scenarios are not promises; they are model states.
    up=max(0,min(1,0.5+score/160))
    down=max(0,min(1,0.5-score/160))
    rng=max(0,1-abs(score)/80)
    total=up+down+rng
    return regime,score,100*up/total,100*rng/total,100*down/total

def card_level(label, row, color):
    if row is None: return
    st.markdown(f"**{label}**  \n`{row.strike:,.0f}`  **{getattr(row,'sup_score',getattr(row,'res_score',0)):.0f}/100**")

def render_index(name, token, weights, full_weights):
    cfg=INDEXES[name]
    # Index LTP.
    iq=ltp_quotes(token,[cfg["key"]])
    raw=iq.get(cfg["key"]) or iq.get(cfg["key"].replace("|",":")) or {}
    spot=float(raw.get("last_price") or 0)
    cp=float(raw.get("cp") or 0)
    chg=((spot/cp)-1)*100 if spot and cp else 0

    chain=option_chain(token,cfg["key"])
    odf=build_option_df(chain)
    if odf.empty:
        st.error(f"{name}: option chain unavailable.")
        return

    # Keep a session-start OI snapshot so the dashboard also shows
    # intraday/session OI change, in addition to Upstox's day-over-day OI.
    base_key = f"oi_base_{name}"
    current_oi = {
        float(r.strike): {"ce": float(r.ce_oi), "pe": float(r.pe_oi)}
        for _, r in odf.iterrows()
    }
    if base_key not in st.session_state:
        st.session_state[base_key] = current_oi
    baseline = st.session_state[base_key]
    odf["ce_session_doi"] = odf.apply(
        lambda r: r.ce_oi - baseline.get(float(r.strike), {}).get("ce", r.ce_oi), axis=1
    )
    odf["pe_session_doi"] = odf.apply(
        lambda r: r.pe_oi - baseline.get(float(r.strike), {}).get("pe", r.pe_oi), axis=1
    )

    level,scored=level_engine(odf,spot,cfg["step"])
    flow,breadth,coverage=0,0,0
    stock_df,flow,breadth,coverage=session_pressure(name,weights,token)
    regime,score,p_up,p_range,p_down=signal_for(name,spot,flow,breadth,level,scored)

    st.markdown(f"## {'🟢' if score>12 else '🔴' if score<-12 else '🟡'} {name}")
    a,b,c,d,e=st.columns(5)
    a.metric("LTP",f"{spot:,.2f}",f"{chg:+.2f}%")
    b.metric("Flow impact",f"{flow:+.3f}%")
    c.metric("Breadth",f"{breadth:.0f}%")
    d.metric("PCR (near ATM)",f"{level['pcr']:.2f}" if np.isfinite(level["pcr"]) else "—")
    e.metric("Model",f"{score:+.0f}/100")
    st.caption(f"Coverage: {coverage:.1f}% of configured index weight • {'full file' if full_weights else 'reference top constituents'}")

    # Reversal map
    st.markdown("### 🎯 Live reversal map — our independent EOS / EOR model")
    m1,m2,m3=st.columns([1,1.4,1])
    with m1:
        st.markdown("**🔴 EOR + 1**")
        st.markdown(f"### {level['eor1']:,.0f}")
        st.markdown("**🔴 EOR**")
        st.markdown(f"### {level['eor']:,.0f}")
    with m2:
        st.markdown("### CURRENT")
        st.markdown(f"# {spot:,.2f}")
        st.caption("Above EOR = upside acceptance test • Below EOS = downside acceptance test")
        st.progress(max(0,min(1,(spot-level["eos"])/max(level["eor"]-level["eos"],1))))
    with m3:
        st.markdown("**🟢 EOS**")
        st.markdown(f"### {level['eos']:,.0f}")
        st.markdown("**🟢 EOS - 1**")
        st.markdown(f"### {level['eos1']:,.0f}")

    if spot>level["eor"]:
        state="🟢 ABOVE EOR — bullish acceptance"
    elif spot<level["eos"]:
        state="🔴 BELOW EOS — bearish acceptance"
    else:
        state="🟡 BETWEEN EOS/EOR — rotation/range"
    st.info(state)

    # Top levels
    l,r=st.columns(2)
    with l:
        st.markdown("#### 🟢 Strongest supports")
        sup=level["support"]
        if sup:
            sdf=pd.DataFrame([{
                "Strike":r.strike,"Score":r.sup_score,
                "PE OI":r.pe_oi,"PE ΔOI":r.pe_doi,
                "PE LTP":r.pe_ltp,"PE ΔPremium %":r.pe_prem_chg
            } for r in sup])
            st.dataframe(sdf.round(2),use_container_width=True,hide_index=True)
    with r:
        st.markdown("#### 🔴 Strongest resistances")
        res=level["resistance"]
        if res:
            rdf=pd.DataFrame([{
                "Strike":r.strike,"Score":r.res_score,
                "CE OI":r.ce_oi,"CE ΔOI":r.ce_doi,
                "CE LTP":r.ce_ltp,"CE ΔPremium %":r.ce_prem_chg
            } for r in res])
            st.dataframe(rdf.round(2),use_container_width=True,hide_index=True)

    # Next move
    st.markdown("### 🔮 Next-move model")
    n1,n2,n3,n4=st.columns(4)
    n1.metric("Primary",regime)
    n2.metric("Upside scenario",f"{p_up:.0f}%")
    n3.metric("Range scenario",f"{p_range:.0f}%")
    n4.metric("Downside scenario",f"{p_down:.0f}%")

    reasons=[]
    reasons.append(("Stock flow", "bullish" if flow>0.03 else "bearish" if flow<-0.03 else "mixed"))
    reasons.append(("Breadth", "bullish" if breadth>55 else "bearish" if breadth<45 else "mixed"))
    reasons.append(("OI structure", "bullish" if level["structure"]>8 else "bearish" if level["structure"]<-8 else "mixed"))
    reasons.append(("Price location", "bullish" if spot>level["eor"] else "bearish" if spot<level["eos"] else "range"))
    st.write(" • ".join([f"**{a}:** {b}" for a,b in reasons]))
    st.caption("Scenario percentages are normalized model outputs, not statistical guarantees or trade recommendations.")

    # Stock movers
    st.markdown(f"### 📈 What is moving {name}?")
    if stock_df.empty:
        st.warning("No constituent quote data returned.")
    else:
        x,y=st.columns(2)
        with x:
            st.markdown("**🟢 Pushing higher**")
            st.dataframe(stock_df[stock_df.impact_pct>0].head(8)[
                ["symbol","weight_pct","move_pct","impact_pct","ltp"]
            ].rename(columns={"symbol":"Stock","weight_pct":"Weight %","move_pct":"Move %",
                              "impact_pct":"Index impact %","ltp":"LTP"}).round(3),
                         use_container_width=True,hide_index=True)
        with y:
            st.markdown("**🔴 Dragging lower**")
            st.dataframe(stock_df[stock_df.impact_pct<0].sort_values("impact_pct").head(8)[
                ["symbol","weight_pct","move_pct","impact_pct","ltp"]
            ].rename(columns={"symbol":"Stock","weight_pct":"Weight %","move_pct":"Move %",
                              "impact_pct":"Index impact %","ltp":"LTP"}).round(3),
                         use_container_width=True,hide_index=True)

        top5=stock_df.reindex(stock_df.impact_pct.abs().sort_values(ascending=False).index).head(5)
        st.caption("Top impact names: " + ", ".join([f"{r.symbol} {r.impact_pct:+.3f}%" for _,r in top5.iterrows()]))

    # Option pulse
    st.markdown("### ⚡ OI Pulse — index only")
    near=scored.iloc[(scored["strike"]-spot).abs().argsort()[:15]].copy()
    near=near.sort_values("strike")
    pulse=near[["strike","ce_oi","ce_doi","ce_session_doi","ce_ltp","ce_prem_chg",
                "pe_ltp","pe_prem_chg","pe_session_doi","pe_doi","pe_oi"]].rename(columns={
        "strike":"Strike","ce_oi":"CE OI","ce_doi":"CE ΔOI(day)",
        "ce_session_doi":"CE ΔOI(session)","ce_ltp":"CE LTP",
        "ce_prem_chg":"CE Prem %","pe_ltp":"PE LTP","pe_prem_chg":"PE Prem %",
        "pe_session_doi":"PE ΔOI(session)","pe_doi":"PE ΔOI(day)","pe_oi":"PE OI"})
    st.dataframe(pulse.round(2),use_container_width=True,hide_index=True)

    with st.expander("Math used — read this before trading"):
        st.markdown("""
### Stock impact
`Index impact ≈ index weight × constituent return / 100`

### Our EOS / EOR engine
We score each nearby strike using:
- **55% OI concentration**
- **30% fresh writing evidence** (positive ΔOI + falling option premium)
- **15% proximity to spot**

The strongest PE-supported strike below spot becomes **EOS**.
The strongest CE-supported strike above spot becomes **EOR**.
`EOS-1` and `EOR+1` are the next index strike-step extension zones.

### Next-move model
The directional score combines:
- **35% stock-flow pressure**
- **20% breadth**
- **30% option structure**
- **15% location inside EOS/EOR**

The model is intentionally transparent. It is a scenario engine, not a claim of certainty.
""")

def main():
    token=token_from_secrets()
    with st.sidebar:
        st.title("⚡ Nifty Quant Pulse")
        if not token:
            token=st.text_input("Upstox token",type="password")
        else:
            st.success("Upstox token loaded")
        refresh=st.slider("Refresh (seconds)",3,15,5)
        uploaded_n=st.file_uploader("Nifty weights CSV",type=["csv"])
        uploaded_b=st.file_uploader("Bank Nifty weights CSV",type=["csv"])
        st.caption("CSV columns: symbol, weight_pct")
        st.markdown("---")
        st.markdown("**Live mode:** dashboard reruns automatically.")
        st.caption(f"Last render: {datetime.now(IST).strftime('%H:%M:%S IST')}")

    if not token:
        st.info("Add your Upstox token in Streamlit Secrets as UPSTOX_ACCESS_TOKEN.")
        st.stop()

    nw,nfull=load_weights("NIFTY 50",uploaded_n)
    bw,bfull=load_weights("BANK NIFTY",uploaded_b)

    st.title("⚡ NIFTY / BANK NIFTY PULSE")
    st.caption("Live LTP • stock-flow impact • OI pulse • EOS/EOR-style reversal map • next-move scenarios")

    # Fragment is native Streamlit auto-rerun; fallback is a manual rerun button
    # for older Streamlit installations.
    @st.fragment(run_every=f"{refresh}s")
    def live_dashboard():
        tabs=st.tabs(["NIFTY 50","BANK NIFTY","LTP CALCULATOR"])
        with tabs[0]:
            render_index("NIFTY 50",token,nw,nfull)
        with tabs[1]:
            render_index("BANK NIFTY",token,bw,bfull)
        with tabs[2]:
            st.subheader("LTP / Move Calculator")
            c1,c2,c3=st.columns(3)
            spot=c1.number_input("Underlying LTP",value=24000.0,step=50.0)
            move=c2.number_input("Underlying move",value=100.0,step=50.0)
            delta=c3.number_input("Option delta",value=0.50,min_value=-1.0,max_value=1.0,step=0.01)
            option_ltp=st.number_input("Option LTP",value=100.0,step=1.0)
            estimated=option_ltp+delta*move
            st.metric("Linear option LTP estimate",f"₹{estimated:,.2f}")
            st.caption("First-order delta estimate; gamma, IV, theta, slippage and spread are not modeled.")

    live_dashboard()
    return

if __name__=="__main__":
    main()
