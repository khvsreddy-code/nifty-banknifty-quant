"""V10 live entrypoint — stable live feed + mounted Lightweight Charts.

This loader pins the current feature-complete engine to commit 1e85cde7...
and applies only the live-transport/chart fixes. No Upstox token is stored here.
"""
import requests

SOURCE_URL = "https://raw.githubusercontent.com/khvsreddy-code/nifty-banknifty-quant/1e85cde7e2c76cf6bb1787faf52cc622597c201f/app.py"
r = requests.get(SOURCE_URL, timeout=25)
r.raise_for_status()
legacy = r.text
if not legacy.startswith("import math"):
    raise RuntimeError("Pinned legacy app source was not returned.")

def patch(old, new, label):
    global legacy
    n = legacy.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {n}")
    legacy = legacy.replace(old, new, 1)

# 1) One process-lifetime Upstox stream instead of a new websocket on every rerun.
patch(
"""def live_feed_resource(token):
    return LiveFeedCache(token)""",
"""@st.cache_resource(show_spinner=False)
def live_feed_resource(token):
    return LiveFeedCache(token)""",
"live-feed cache")

# 2) Remember the last WS message and add a V3 LTP watchdog.
patch(
"""        self.last_publish={}
        self.symbol_by_key={str(cfg.get("key")): name for name,cfg in INDEXES.items() if cfg.get("key")}""",
"""        self.last_publish={}
        self.last_message_at=0.0
        self.rest_thread=None
        self.rest_stop=threading.Event()
        self.symbol_by_key={str(cfg.get("key")): name for name,cfg in INDEXES.items() if cfg.get("key")}""",
"feed state")

patch(
"""        with self.lock:
            for k,v in feeds.items():
                self.data[k]=v
            self.status="connected" """.rstrip(),
"""        with self.lock:
            for k,v in feeds.items():
                self.data[k]=v
            self.status="connected"
            self.last_message_at=time.time()""",
"feed heartbeat")

patch(
"""    def start(self, keys):
""",
"""    def _rest_fallback_loop(self):
        while not self.rest_stop.wait(1.0):
            try:
                if not self.keys:
                    continue
                last_msg=float(getattr(self,"last_message_at",0.0) or 0.0)
                if self.status=="connected" and time.time()-last_msg < 2.5:
                    continue
                r=requests.get(
                    f"{API3}/market-quote/ltp",
                    headers=headers(self.token),
                    params={"instrument_key":",".join(self.keys)},
                    timeout=4,
                )
                if not r.ok:
                    self.error=f"REST LTP fallback HTTP {r.status_code}"
                    continue
                body=r.json() if r.content else {}
                data=body.get("data",{}) if isinstance(body,dict) else {}
                got=0
                for key in self.keys:
                    q=quote_from_data(data,key)
                    price=num(q.get("last_price")); cp=num(q.get("cp"))
                    if price<=0:
                        continue
                    feed={"ltpc":{"ltp":price,"cp":cp}}
                    with self.lock:
                        self.data[key]=feed
                    self._publish_tick(key,feed)
                    got+=1
                if got:
                    self.status="rest-fallback"
                    self.error="WebSocket stale — V3 LTP fallback active"
            except Exception as exc:
                self.error=str(exc)

    def start(self, keys):
""",
"REST watchdog")

patch(
"""        self.thread=threading.Thread(target=runner,daemon=True)
        self.thread.start()

    def snapshot(self):""",
"""        self.thread=threading.Thread(target=runner,daemon=True)
        self.thread.start()
        if not self.rest_thread or not self.rest_thread.is_alive():
            self.rest_stop.clear()
            self.rest_thread=threading.Thread(target=self._rest_fallback_loop,daemon=True)
            self.rest_thread.start()

    def snapshot(self):""",
"watchdog start")

# 3) Always keep the chart component mounted and pass the selected timeframe.
patch(
"""            _chart_render_key=f"chart_rendered_{name}_{_tf}"
            if not st.session_state.get(_chart_render_key):
                render_upstox_tv_chart(_tv_candles, spot, levels, name)
                st.session_state[_chart_render_key]=True
            else:
                st.caption("🟢 Live chart stream active — chart is intentionally not rebuilt on each pulse.")""",
"""            render_upstox_tv_chart(_tv_candles, spot, levels, name, _tf_options[_tf])
            st.caption("🟢 Live chart stream active — browser updates arrive from the V3 live-tick bus; Streamlit analytics may pulse independently.")""",
"chart mount")

# 4) Update the live candle and keep the viewport at the live edge.
patch(
"""  try{
    cs.update(liveBar);
    ls.update({time:bucket,value:price});
    if(overlays.ema20) overlays.ema20.update({time:bucket,value:price});
  }catch(e){}
  const badge=document.querySelector('.live');
  if(badge) badge.textContent='● LIVE '+price.toLocaleString('en-IN',{maximumFractionDigits:2});""",
"""  try{
    cs.update(liveBar);
    ls.update({time:bucket,value:price});
    if(overlays.ema20) overlays.ema20.update({time:bucket,value:price});
    if(overlays.ema50) overlays.ema50.update({time:bucket,value:price});
    if(overlays.vwap) overlays.vwap.update({time:bucket,value:price});
    if(overlays.bbMid) overlays.bbMid.update({time:bucket,value:price});
    if(window.followLive!==false) chart.timeScale().scrollToRealTime();
  }catch(e){}
  window.lastLiveAt=Date.now();
  const badge=document.querySelector('.live');
  if(badge){
    badge.textContent='● LIVE '+price.toLocaleString('en-IN',{maximumFractionDigits:2});
    badge.style.color='#61d4a5';
    badge.style.borderColor='#1e624b';
    badge.style.background='#0b2a20';
  }""",
"chart tick update")

# 5) A stale watchdog makes a dead feed obvious instead of freezing silently.
patch(
"""startLiveBridge();
setInterval(pollLatestTick,1000);
pollLatestTick();""",
"""window.lastLiveAt=0;
window.followLive=true;
mainEl.addEventListener('wheel',()=>{window.followLive=false},{passive:true});
setInterval(()=>{
  const badge=document.querySelector('.live');
  if(!badge) return;
  if(window.lastLiveAt && Date.now()-window.lastLiveAt>3000){
    badge.textContent='● STALE — waiting for feed';
    badge.style.color='#fbbf24';
    badge.style.borderColor='#7c5d17';
    badge.style.background='#2a2110';
  }
},500);
startLiveBridge();
setInterval(pollLatestTick,1000);
pollLatestTick();""",
"chart stale watchdog")

# 6) Normal TradingView-style last-price line.
old="""const cs=chart.addCandlestickSeries({upColor:'#22c55e',downColor:'#ef4444',borderUpColor:'#22c55e',borderDownColor:'#ef4444',wickUpColor:'#22c55e',wickDownColor:'#22c55e'});cs.setData(DATA);"""
new="""const cs=chart.addCandlestickSeries({upColor:'#22c55e',downColor:'#ef4444',borderUpColor:'#22c55e',borderDownColor:'#ef4444',wickUpColor:'#22c55e',wickDownColor:'#22c55e',lastValueVisible:true,priceLineVisible:true});cs.setData(DATA);"""
if old in legacy:
    legacy = legacy.replace(old, new, 1)

exec(compile(legacy, SOURCE_URL, "exec"), globals(), globals())
