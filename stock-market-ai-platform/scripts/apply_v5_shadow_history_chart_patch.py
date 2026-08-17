from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "webapp/app.py"
TEMPLATE = ROOT / "webapp/templates/index.html"
READER = ROOT / "webapp/services/v5_shadow_history_service.py"
JS = ROOT / "webapp/static/js/v5_shadow_history_chart.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[SKIP] {label}")
        return text
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


READER.write_text(r'''"""Read-only history reader for the V4/V5/SPY diagnostic comparison journal."""

from __future__ import annotations

import json
from pathlib import Path

JOURNAL_PATH = Path("data/paper_trading/v5_shadow/comparison_journal.jsonl")


def get_v5_shadow_history():
    rows = []
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append({
                "timestamp_utc": row.get("timestamp_utc"),
                "v4_normalized_equity": row.get("v4_normalized_equity"),
                "v5_shadow_equity": row.get("v5_shadow_equity"),
                "spy_normalized_equity": row.get("spy_normalized_equity"),
                "v5_vs_v4_pct_points": row.get("v5_vs_v4_pct_points"),
                "v5_vs_spy_pct_points": row.get("v5_vs_spy_pct_points"),
            })

    return {
        "journal_type": "V4_V5_SPY_DIAGNOSTIC_COMPARISON",
        "comparison_scope": "NON_OFFICIAL_DIAGNOSTIC",
        "observation_count": len(rows),
        "rows": rows,
        "official_holdout_excluded": True,
        "brokerage_orders": False,
    }
''', encoding="utf-8")
print("[APPLY] V5 shadow history reader")

JS.write_text(r'''(() => {
  const svg = document.getElementById('v5-shadow-history-chart');
  if (!svg) return;

  const tooltip = document.getElementById('v5-shadow-history-tooltip');
  const status = document.getElementById('v5-shadow-history-status');
  const countEl = document.getElementById('v5-shadow-history-count');
  const latestEl = document.getElementById('v5-shadow-history-latest');
  const NS='http://www.w3.org/2000/svg';

  const money = v => `$${Number(v).toLocaleString(undefined,{minimumFractionDigits:0,maximumFractionDigits:0})}`;
  const dt = v => new Date(v);
  const fmt = v => dt(v).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});

  function node(name, attrs={}){
    const el=document.createElementNS(NS,name);
    Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));
    return el;
  }

  function render(rows){
    svg.innerHTML='';
    if(countEl) countEl.textContent=String(rows.length);
    if(latestEl) latestEl.textContent=rows.length?fmt(rows[rows.length-1].timestamp_utc):'—';
    if(!rows.length){ if(status) status.textContent='AWAITING JOURNAL OBSERVATIONS'; return; }

    const W=1000,H=360,L=72,R=24,T=28,B=48;
    const vals=[];
    rows.forEach(r=>['v4_normalized_equity','v5_shadow_equity','spy_normalized_equity'].forEach(k=>{
      const x=Number(r[k]); if(Number.isFinite(x)) vals.push(x);
    }));
    if(!vals.length) return;
    let ymin=Math.min(...vals), ymax=Math.max(...vals);
    const pad=Math.max((ymax-ymin)*0.18,25);
    ymin-=pad; ymax+=pad;
    const x=i=>L+(rows.length===1?0.5:(i/(rows.length-1)))*(W-L-R);
    const y=v=>T+(ymax-v)/(ymax-ymin)*(H-T-B);

    for(let i=0;i<5;i++){
      const yy=T+i*(H-T-B)/4;
      svg.appendChild(node('line',{x1:L,y1:yy,x2:W-R,y2:yy,stroke:'rgba(145,166,194,.16)','stroke-width':1}));
      const val=ymax-i*(ymax-ymin)/4;
      const txt=node('text',{x:L-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':12}); txt.textContent=money(val); svg.appendChild(txt);
    }

    const series=[
      ['v4_normalized_equity','V4','#36d8ff'],
      ['v5_shadow_equity','V5 Shadow','#39e3a1'],
      ['spy_normalized_equity','SPY','#efc56b'],
    ];
    series.forEach(([key,label,color])=>{
      const pts=rows.map((r,i)=>`${x(i)},${y(Number(r[key]))}`).join(' ');
      svg.appendChild(node('polyline',{points:pts,fill:'none',stroke:color,'stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'}));
      const g=node('g',{}); const cx=series.indexOf(series.find(s=>s[0]===key))*150+L;
      g.appendChild(node('line',{x1:cx,y1:12,x2:cx+24,y2:12,stroke:color,'stroke-width':4}));
      const tx=node('text',{x:cx+32,y:16,fill:'#f2f6ff','font-size':12,'font-weight':700}); tx.textContent=label; g.appendChild(tx); svg.appendChild(g);
    });

    const tickIndexes=[0,Math.floor((rows.length-1)/2),rows.length-1].filter((v,i,a)=>a.indexOf(v)===i);
    tickIndexes.forEach(i=>{ const t=node('text',{x:x(i),y:H-18,'text-anchor':'middle',fill:'#91a6c2','font-size':12}); t.textContent=fmt(rows[i].timestamp_utc); svg.appendChild(t); });

    const overlay=node('rect',{x:L,y:T,width:W-L-R,height:H-T-B,fill:'transparent'}); svg.appendChild(overlay);
    const guide=node('line',{x1:L,y1:T,x2:L,y2:H-B,stroke:'rgba(242,246,255,.35)','stroke-width':1,display:'none'}); svg.appendChild(guide);

    overlay.addEventListener('mousemove',e=>{
      const box=svg.getBoundingClientRect(); const px=(e.clientX-box.left)/box.width*W;
      let i=rows.length===1?0:Math.round((px-L)/(W-L-R)*(rows.length-1)); i=Math.max(0,Math.min(rows.length-1,i));
      guide.setAttribute('x1',x(i)); guide.setAttribute('x2',x(i)); guide.setAttribute('display','block');
      const r=rows[i];
      if(tooltip){
        tooltip.style.display='block'; tooltip.style.left=`${Math.min(e.offsetX+14,box.width-210)}px`; tooltip.style.top=`${Math.max(e.offsetY-72,8)}px`;
        tooltip.innerHTML=`<strong>${fmt(r.timestamp_utc)}</strong><br>V4 ${money(r.v4_normalized_equity)}<br>V5 ${money(r.v5_shadow_equity)}<br>SPY ${money(r.spy_normalized_equity)}`;
      }
    });
    overlay.addEventListener('mouseleave',()=>{guide.setAttribute('display','none'); if(tooltip)tooltip.style.display='none';});
    if(status) status.textContent=rows.length<2?'1 OBSERVATION · MORE HISTORY WILL APPEAR HOURLY':'HISTORY READY';
  }

  async function load(){
    try{
      const r=await fetch('/api/v5-shadow-history',{credentials:'same-origin',cache:'no-store'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      const d=await r.json(); render(d.rows||[]);
    }catch(err){ if(status){status.textContent='HISTORY ERROR';status.className='negative';} console.warn('[V5 SHADOW HISTORY]',err); }
  }
  load();
  window.setInterval(load,60000);
})();
''', encoding="utf-8")
print("[APPLY] V5 shadow history chart browser module")

app = APP.read_text(encoding="utf-8")
app = replace_once(
    app,
    'from webapp.services.v5_shadow_portfolio_service import get_v5_shadow_comparison  # noqa: E402\n',
    'from webapp.services.v5_shadow_portfolio_service import get_v5_shadow_comparison  # noqa: E402\nfrom webapp.services.v5_shadow_history_service import get_v5_shadow_history  # noqa: E402\n',
    'V5 shadow history service import',
)
app = replace_once(
    app,
    "                '<script src=\"/static/js/v5_shadow_comparison.js\" defer></script>',\n",
    "                '<script src=\"/static/js/v5_shadow_comparison.js\" defer></script>',\n                '<script src=\"/static/js/v5_shadow_history_chart.js\" defer></script>',\n",
    'V5 shadow history chart script',
)
route_marker = '''@app.route("/api/v5-shadow-comparison")\n@login_required\ndef api_v5_shadow_comparison():\n    return jsonify(get_v5_shadow_comparison())\n'''
route_new = route_marker + '''\n\n@app.route("/api/v5-shadow-history")\n@login_required\ndef api_v5_shadow_history():\n    return jsonify(get_v5_shadow_history())\n'''
app = replace_once(app, route_marker, route_new, 'V5 shadow history API')
APP.write_text(app, encoding="utf-8")

tpl = TEMPLATE.read_text(encoding="utf-8")
style_marker = '''<style id="v5-shadow-comparison-style">\n.v5-shadow-holdings{display:grid;gap:8px;margin-top:12px}.v5-shadow-row{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:12px 14px;border:1px solid rgba(120,155,205,.15);border-radius:12px;background:rgba(8,20,36,.45)}.v5-shadow-row>div:last-child{text-align:right}\n</style>'''
style_new = style_marker + '''\n<style id="v5-shadow-history-style">\n.v5-shadow-history-card{margin-top:18px;padding:18px;border:1px solid var(--border);border-radius:18px;background:rgba(8,20,36,.58)}.v5-shadow-history-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;flex-wrap:wrap}.v5-shadow-history-wrap{position:relative;height:360px;margin-top:12px}.v5-shadow-history-wrap svg{width:100%;height:100%;display:block}.v5-shadow-history-meta{display:flex;gap:12px;flex-wrap:wrap}.v5-shadow-history-tooltip{position:absolute;display:none;pointer-events:none;background:#071525;border:1px solid var(--border);padding:8px 10px;border-radius:9px;font-size:.78rem;box-shadow:0 10px 25px rgba(0,0,0,.35);z-index:10}\n</style>'''
tpl = replace_once(tpl, style_marker, style_new, 'V5 shadow history chart styles')
insert_marker = '''  <div class="grid grid-2" style="margin-top:18px">\n    <div>\n      <div class="label">V5 SHADOW HOLDINGS</div>'''
chart = '''  <div class="v5-shadow-history-card">\n    <div class="v5-shadow-history-head">\n      <div><div class="label">COMPARISON HISTORY</div><h3>V4 vs V5 vs SPY — Common Shadow Start</h3><div class="muted">Normalized equity from the append-only hourly diagnostic journal. All three lines begin from the same comparison baseline.</div></div>\n      <div class="v5-shadow-history-meta"><div class="metric"><span>OBSERVATIONS</span><strong id="v5-shadow-history-count">—</strong></div><div class="metric"><span>LATEST</span><strong id="v5-shadow-history-latest" style="font-size:.9rem">—</strong></div></div>\n    </div>\n    <div id="v5-shadow-history-status" class="mode" style="margin-top:12px">LOADING HISTORY</div>\n    <div class="v5-shadow-history-wrap"><svg id="v5-shadow-history-chart" viewBox="0 0 1000 360" preserveAspectRatio="none" aria-label="V4 versus V5 versus SPY normalized equity history"></svg><div id="v5-shadow-history-tooltip" class="v5-shadow-history-tooltip"></div></div>\n    <div class="muted">Diagnostic pre-holdout history only. This chart does not write to or count toward the official Sep 1+ V5 evaluation.</div>\n  </div>\n\n'''
tpl = replace_once(tpl, insert_marker, chart + insert_marker, 'V4 V5 SPY comparison history panel')
TEMPLATE.write_text(tpl, encoding="utf-8")

print("V4/V5/SPY comparison history chart patch complete.")
print("Read-only dashboard history from the diagnostic journal; frozen models, V4 state, official holdout, and brokerage settings are unchanged.")
