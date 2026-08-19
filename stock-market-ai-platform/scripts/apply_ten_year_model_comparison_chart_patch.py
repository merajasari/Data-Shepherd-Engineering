"""Apply a read-only ten-year stock-model reconstruction comparison chart.

This patch does not backdate or modify genuine paper journals. It adds a
comparison builder that consumes existing causal/research reconstruction
artifacts and a dashboard chart that displays every valid model on one common
$100,000 scale together with SPY.
"""

from pathlib import Path

ROOT = Path('.')

SERVICE = r'''"""Read-only service for historical stock-model comparison artifacts."""
from __future__ import annotations
import json
from pathlib import Path

COMPARISON_PATH = Path("data/model/model_comparison/ten_year_comparison.json")


def load_ten_year_model_comparison():
    if not COMPARISON_PATH.exists():
        return {
            "status": "MISSING",
            "message": "Run PYTHONPATH=. python -m ml.run_ten_year_model_comparison",
            "starting_equity": 100000.0,
            "series": [],
            "rows": [],
        }
    try:
        data = json.loads(COMPARISON_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "ERROR", "message": str(exc), "series": [], "rows": []}
    data["status"] = "READY"
    return data
'''

RUNNER = r'''"""Build one common historical equity comparison for valid stock models.

Scientific/display contract
---------------------------
* Research reconstruction only: genuine paper state and journals are untouched.
* Every displayed strategy is normalized to $100,000 at its first valid point.
* V4 uses its existing causal full-history walk-forward reconstruction artifact.
* V5 uses the already-generated development portfolio contract/results; it is not
  retroactively evaluated with the final frozen 2026 model.
* V8 uses the fixed Phase-5 DISTANCE_ONLY strategy at the pre-registered 10-bps
  cost assumption, combining all five staggered cohorts equally.
* SPY is normalized to $100,000 at the earliest displayed strategy date.
* V6/V7 are intentionally not invented: if no finalized executable portfolio
  reconstruction exists, no line is fabricated for them.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import numpy as np
import pandas as pd

STARTING_EQUITY = 100000.0
YEARS = 10
OUTPUT = Path("data/model/model_comparison/ten_year_comparison.json")
FEATURE_ROOT = Path("data/features/stocks")


def _norm(rows, ts_col="timestamp", value_col="equity"):
    x = pd.DataFrame(rows).copy()
    if x.empty:
        return x
    x[ts_col] = pd.to_datetime(x[ts_col], utc=True)
    x[value_col] = pd.to_numeric(x[value_col], errors="coerce")
    x = x.dropna(subset=[ts_col, value_col]).sort_values(ts_col)
    if x.empty or float(x[value_col].iloc[0]) == 0:
        return pd.DataFrame()
    x["equity"] = STARTING_EQUITY * x[value_col] / float(x[value_col].iloc[0])
    return x[[ts_col, "equity"]].rename(columns={ts_col:"timestamp_utc"})


def _v4_curve():
    p = Path("data/model/v4/full_history_equity.json")
    if not p.exists():
        return None, "missing data/model/v4/full_history_equity.json; run ml.run_v4_full_history_reconstruction"
    d = json.loads(p.read_text())
    hist = d.get("history", [])
    x = _norm(hist, "timestamp", "equity")
    return x, None if not x.empty else "V4 artifact has no usable history"


def _v5_curve():
    p = Path("data/model/v5/phase3/portfolio_daily.csv")
    if not p.exists():
        return None, "missing V5 Phase-3 development portfolio artifact"
    x = pd.read_csv(p)
    required = {"timestamp_utc", "gross_return_5d", "turnover"}
    if not required.issubset(x.columns):
        return None, "V5 Phase-3 portfolio artifact is missing required columns"
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x = x.sort_values("timestamp_utc")
    # V5's robustness work uses 10 bps as a central realistic cost assumption.
    net = pd.to_numeric(x["gross_return_5d"], errors="coerce") - pd.to_numeric(x["turnover"], errors="coerce") * 10.0 / 10000.0
    x["equity"] = STARTING_EQUITY * (1.0 + net.fillna(0.0)).cumprod()
    return x[["timestamp_utc", "equity"]], None


def _v8_curve():
    p = Path("data/model/v8/phase5/economic_period_results.csv")
    if not p.exists():
        return None, "missing V8 Phase-5 economic-period artifact"
    x = pd.read_csv(p)
    required = {"score_id", "cohort_offset", "exit_timestamp_utc", "cost_bps_per_dollar_traded", "net_portfolio_return"}
    if not required.issubset(x.columns):
        return None, "V8 Phase-5 artifact is missing required columns"
    x = x[(x["score_id"] == "DISTANCE_ONLY") & (x["cost_bps_per_dollar_traded"] == 10)].copy()
    if x.empty:
        return None, "V8 Phase-5 has no DISTANCE_ONLY observations at 10 bps"
    x["exit_timestamp_utc"] = pd.to_datetime(x["exit_timestamp_utc"], utc=True)
    frames = []
    for offset, g in x.groupby("cohort_offset", sort=True):
        g = g.sort_values("exit_timestamp_utc").copy()
        g["cohort_wealth"] = (1.0 + pd.to_numeric(g["net_portfolio_return"], errors="coerce").fillna(0.0)).cumprod()
        frames.append(g[["exit_timestamp_utc", "cohort_wealth"]].rename(columns={"cohort_wealth":f"c{int(offset)}"}))
    if not frames:
        return None, "V8 Phase-5 produced no cohort curves"
    z = frames[0]
    for f in frames[1:]:
        z = z.merge(f, on="exit_timestamp_utc", how="outer")
    z = z.sort_values("exit_timestamp_utc").ffill()
    ccols = [c for c in z.columns if c.startswith("c")]
    # Each staggered sleeve receives 20% of starting capital. Sleeves that have
    # not started yet remain at cash=1.0 rather than being silently dropped.
    z[ccols] = z[ccols].fillna(1.0)
    z["equity"] = STARTING_EQUITY * z[ccols].mean(axis=1)
    return z[["exit_timestamp_utc", "equity"]].rename(columns={"exit_timestamp_utc":"timestamp_utc"}), None


def _spy_curve(start, end):
    candidates = sorted(FEATURE_ROOT.glob("SPY/*.parquet"))
    if not candidates:
        return None, "SPY feature parquet not found"
    df = pd.read_parquet(candidates[0]).copy()
    ts = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    price = "close" if "close" in df.columns else None
    if not price:
        return None, "SPY feature data has no close column"
    df["timestamp_utc"] = pd.to_datetime(df[ts], utc=True)
    df["close"] = pd.to_numeric(df[price], errors="coerce")
    df = df[(df["timestamp_utc"] >= start) & (df["timestamp_utc"] <= end)].dropna(subset=["close"]).sort_values("timestamp_utc")
    if df.empty:
        return None, "SPY has no observations in comparison window"
    df["equity"] = STARTING_EQUITY * df["close"] / float(df["close"].iloc[0])
    return df[["timestamp_utc", "equity"]], None


def _stats(x):
    if x is None or x.empty:
        return None
    e = x["equity"].astype(float)
    peak = e.cummax()
    dd = e / peak - 1.0
    years = max((x["timestamp_utc"].iloc[-1] - x["timestamp_utc"].iloc[0]).days / 365.25, 1/365.25)
    total = e.iloc[-1] / e.iloc[0] - 1.0
    return {
        "start": x["timestamp_utc"].iloc[0].isoformat(),
        "end": x["timestamp_utc"].iloc[-1].isoformat(),
        "observations": int(len(x)),
        "ending_equity": round(float(e.iloc[-1]), 2),
        "total_return_pct": round(float(total * 100.0), 4),
        "cagr_pct": round(float(((e.iloc[-1]/e.iloc[0]) ** (1.0/years) - 1.0) * 100.0), 4),
        "max_drawdown_pct": round(float(dd.min() * 100.0), 4),
    }


def main():
    builders = [("V4", _v4_curve), ("V5", _v5_curve), ("V8", _v8_curve)]
    curves, exclusions = {}, []
    for model_id, fn in builders:
        try:
            curve, reason = fn()
        except Exception as exc:
            curve, reason = None, f"{type(exc).__name__}: {exc}"
        if curve is None or curve.empty:
            exclusions.append({"model_id": model_id, "reason": reason or "no valid curve"})
            continue
        curves[model_id] = curve.copy()

    if not curves:
        raise RuntimeError("No model reconstruction curves are available. Generate the V4/V5/V8 source artifacts first.")

    latest = max(x["timestamp_utc"].max() for x in curves.values())
    requested_start = latest - pd.DateOffset(years=YEARS)
    earliest_available = min(x["timestamp_utc"].min() for x in curves.values())
    chart_start = max(requested_start, earliest_available)
    # Keep each strategy's own first valid date; never fabricate earlier history.
    for k in list(curves):
        curves[k] = curves[k][curves[k]["timestamp_utc"] >= chart_start].copy()
        if not curves[k].empty:
            curves[k]["equity"] = STARTING_EQUITY * curves[k]["equity"] / float(curves[k]["equity"].iloc[0])

    spy, spy_reason = _spy_curve(chart_start, latest)
    if spy is not None and not spy.empty:
        curves["SPY"] = spy
    elif spy_reason:
        exclusions.append({"model_id":"SPY", "reason":spy_reason})

    # Union timestamps, forward-fill only AFTER a model's first actual point.
    timestamps = sorted(set().union(*[set(x["timestamp_utc"]) for x in curves.values()]))
    merged = pd.DataFrame({"timestamp_utc": timestamps}).sort_values("timestamp_utc")
    for model_id, x in curves.items():
        s = x.drop_duplicates("timestamp_utc", keep="last").rename(columns={"equity": model_id})
        merged = merged.merge(s, on="timestamp_utc", how="left")
        first = x["timestamp_utc"].min()
        mask = merged["timestamp_utc"] >= first
        merged.loc[mask, model_id] = merged.loc[mask, model_id].ffill()

    rows = []
    for _, r in merged.iterrows():
        item = {"timestamp_utc": r["timestamp_utc"].isoformat()}
        for model_id in curves:
            v = r.get(model_id)
            item[model_id] = None if pd.isna(v) else round(float(v), 2)
        rows.append(item)

    series = []
    for model_id, x in curves.items():
        series.append({"model_id":model_id, "stats":_stats(x), "reconstruction": model_id != "SPY"})

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "history_type": "RECONSTRUCTED_MODEL_COMPARISON",
        "research_only": True,
        "requested_years": YEARS,
        "starting_equity": STARTING_EQUITY,
        "chart_start": chart_start.isoformat(),
        "chart_end": latest.isoformat(),
        "series": series,
        "excluded": exclusions + [
            {"model_id":"V6", "reason":"No finalized executable V6 portfolio reconstruction registered; not fabricated."},
            {"model_id":"V7", "reason":"Research track closed without a promoted/frozen tradable portfolio; not fabricated."},
        ],
        "rows": rows,
        "safety": {
            "genuine_paper_journal_modified": False,
            "portfolio_state_modified": False,
            "future_holdouts_modified": False,
            "brokerage_orders": False,
            "no_future_history_fabricated": True,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("TEN-YEAR STOCK MODEL COMPARISON")
    print("=" * 80)
    print("Included:", ", ".join(s["model_id"] for s in series))
    print("Chart:", payload["chart_start"], "->", payload["chart_end"])
    for s in series:
        st = s["stats"]
        print(f"{s['model_id']:>4}: ${st['ending_equity']:,.2f} | return={st['total_return_pct']:.2f}% | CAGR={st['cagr_pct']:.2f}% | maxDD={st['max_drawdown_pct']:.2f}%")
    if exclusions:
        print("Unavailable source artifacts:")
        for e in exclusions:
            print(" -", e["model_id"], e["reason"])
    print("Research reconstruction only; genuine paper history unchanged; no orders.")


if __name__ == "__main__":
    main()
'''

JS = r'''(() => {
  const svg=document.getElementById('ten-year-model-comparison-chart');
  if(!svg)return;
  const tip=document.getElementById('ten-year-model-comparison-tooltip');
  const status=document.getElementById('ten-year-model-comparison-status');
  const summary=document.getElementById('ten-year-model-comparison-summary');
  const NS='http://www.w3.org/2000/svg';
  const COLORS=['#36d8ff','#39e3a1','#9b65ff','#ff8f70','#efc56b','#4d8cff'];
  const money=v=>`$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`;
  const fmt=v=>new Date(v).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
  const node=(n,a={})=>{const e=document.createElementNS(NS,n);Object.entries(a).forEach(([k,v])=>e.setAttribute(k,String(v)));return e};

  function render(d){
    const rows=d.rows||[], defs=d.series||[];
    svg.innerHTML='';
    if(!rows.length||!defs.length){if(status)status.textContent=d.message||'NO RECONSTRUCTION DATA';return;}
    const W=1100,H=440,L=82,R=30,T=44,B=58;
    const keys=defs.map(x=>x.model_id);
    const vals=[]; rows.forEach(r=>keys.forEach(k=>{const v=Number(r[k]);if(Number.isFinite(v))vals.push(v)}));
    if(!vals.length)return;
    let lo=Math.min(...vals),hi=Math.max(...vals); const pad=Math.max((hi-lo)*.08,5000); lo=Math.max(0,lo-pad); hi+=pad;
    const x=i=>L+(rows.length===1?.5:i/(rows.length-1))*(W-L-R); const y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
    for(let j=0;j<6;j++){const yy=T+j*(H-T-B)/5;svg.appendChild(node('line',{x1:L,y1:yy,x2:W-R,y2:yy,stroke:'rgba(145,166,194,.15)'}));const tx=node('text',{x:L-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':12});tx.textContent=money(hi-j*(hi-lo)/5);svg.appendChild(tx)}
    defs.forEach((s,idx)=>{const color=COLORS[idx%COLORS.length];let parts=[],current=[];rows.forEach((r,i)=>{const v=Number(r[s.model_id]);if(Number.isFinite(v))current.push(`${x(i)},${y(v)}`);else if(current.length){parts.push(current);current=[]}});if(current.length)parts.push(current);parts.forEach(p=>svg.appendChild(node('polyline',{points:p.join(' '),fill:'none',stroke:color,'stroke-width':s.model_id==='SPY'?2.5:3.2,'stroke-dasharray':s.model_id==='SPY'?'8 5':'none','stroke-linecap':'round','stroke-linejoin':'round'})));const lx=L+(idx%4)*190,ly=16+Math.floor(idx/4)*20;svg.appendChild(node('line',{x1:lx,y1:ly,x2:lx+26,y2:ly,stroke:color,'stroke-width':4}));const tx=node('text',{x:lx+34,y:ly+4,fill:'#f2f6ff','font-size':12,'font-weight':800});tx.textContent=s.model_id;svg.appendChild(tx)});
    [0,.25,.5,.75,1].forEach(p=>{const i=Math.round((rows.length-1)*p),tx=node('text',{x:x(i),y:H-20,'text-anchor':'middle',fill:'#91a6c2','font-size':12});tx.textContent=fmt(rows[i].timestamp_utc);svg.appendChild(tx)});
    const guide=node('line',{x1:L,y1:T,x2:L,y2:H-B,stroke:'rgba(242,246,255,.48)','stroke-width':1.2,display:'none'});svg.appendChild(guide);
    const overlay=node('rect',{x:L,y:T,width:W-L-R,height:H-T-B,fill:'transparent','pointer-events':'all'});svg.appendChild(overlay);
    overlay.addEventListener('mousemove',e=>{const box=svg.getBoundingClientRect(),px=(e.clientX-box.left)/box.width*W;let i=Math.round((px-L)/(W-L-R)*(rows.length-1));i=Math.max(0,Math.min(rows.length-1,i));guide.setAttribute('x1',x(i));guide.setAttribute('x2',x(i));guide.setAttribute('display','block');if(tip){const r=rows[i];tip.style.display='block';tip.style.left=`${Math.min(e.offsetX+14,box.width-235)}px`;tip.style.top=`${Math.max(e.offsetY-90,8)}px`;tip.innerHTML=`<strong>${fmt(r.timestamp_utc)}</strong>`+keys.map(k=>r[k]==null?'':`<div><span>${k}</span><b>${money(r[k])}</b></div>`).join('')}});
    overlay.addEventListener('mouseleave',()=>{guide.setAttribute('display','none');if(tip)tip.style.display='none'});
    if(summary){summary.innerHTML=defs.map(s=>{const st=s.stats||{};return `<div class="metric"><span>${s.model_id} ENDING EQUITY</span><strong>${money(st.ending_equity||0)}</strong><small>${Number(st.total_return_pct||0).toFixed(1)}% total · ${Number(st.max_drawdown_pct||0).toFixed(1)}% max DD</small></div>`}).join('')}
    if(status)status.textContent=`${defs.length} SERIES · ${fmt(d.chart_start)} → ${fmt(d.chart_end)} · RECONSTRUCTED`;
  }
  async function load(){try{const r=await fetch('/api/ten-year-model-comparison',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);render(await r.json())}catch(e){if(status)status.textContent='COMPARISON DATA ERROR';console.warn('[MODEL COMPARISON]',e)}}
  load();
})();
'''

PATCHER_HELPERS = r'''

def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"{label}: anchor not found")
    return text.replace(old, new, 1)
'''

def main():
    Path('webapp/services/model_reconstruction_comparison_service.py').write_text(SERVICE, encoding='utf-8')
    Path('ml/run_ten_year_model_comparison.py').write_text(RUNNER, encoding='utf-8')
    Path('webapp/static/js/ten_year_model_comparison_chart.js').write_text(JS, encoding='utf-8')

    app=Path('webapp/app.py')
    text=app.read_text(encoding='utf-8')
    if 'load_ten_year_model_comparison' not in text:
        import_anchor='from webapp.services.v5_shadow_history_service import'
        pos=text.find(import_anchor)
        if pos < 0:
            # Safe generic insertion before first Flask route.
            route=text.find('@app.route')
            if route < 0: raise RuntimeError('app.py route anchor not found')
            text=text[:route]+'from webapp.services.model_reconstruction_comparison_service import load_ten_year_model_comparison\n\n'+text[route:]
        else:
            line_end=text.find('\n',pos)
            text=text[:line_end+1]+'from webapp.services.model_reconstruction_comparison_service import load_ten_year_model_comparison\n'+text[line_end+1:]
    if '/api/ten-year-model-comparison' not in text:
        anchor='@app.route("/api/v5-shadow-history")'
        pos=text.find(anchor)
        if pos < 0:
            anchor="@app.route('/api/v5-shadow-history')"; pos=text.find(anchor)
        if pos < 0: raise RuntimeError('V5 history route anchor not found')
        route='''@app.route("/api/ten-year-model-comparison")\n@login_required\ndef api_ten_year_model_comparison():\n    return jsonify(load_ten_year_model_comparison())\n\n'''
        text=text[:pos]+route+text[pos:]
    app.write_text(text,encoding='utf-8')

    tpl=Path('webapp/templates/index.html')
    html=tpl.read_text(encoding='utf-8')
    if 'ten-year-model-comparison-chart' not in html:
        style='''\n<style id="ten-year-model-comparison-style">\n.model-comparison-card{margin-top:22px}.model-comparison-wrap{position:relative;height:440px;margin-top:14px}.model-comparison-wrap svg{width:100%;height:100%;display:block;touch-action:none}.model-comparison-tooltip{position:absolute;display:none;pointer-events:none;z-index:30;min-width:200px;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:#071525;box-shadow:0 10px 28px rgba(0,0,0,.38);font-size:.78rem}.model-comparison-tooltip strong{display:block;margin-bottom:6px}.model-comparison-tooltip div{display:flex;justify-content:space-between;gap:18px;margin-top:3px}.model-comparison-tooltip span{color:var(--muted)}.model-comparison-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}.model-comparison-summary small{display:block;color:var(--muted);margin-top:4px}@media(max-width:900px){.model-comparison-summary{grid-template-columns:1fr 1fr}}@media(max-width:600px){.model-comparison-wrap{height:340px}.model-comparison-summary{grid-template-columns:1fr}}\n</style>\n'''
        html=html.replace('</head>',style+'</head>',1)
        card='''\n<section class="card model-comparison-card" id="ten-year-model-comparison-card">\n  <div class="label">HISTORICAL MODEL RECONSTRUCTION</div>\n  <h2>10-Year Stock Model Comparison</h2>\n  <p class="muted">One normalized $100,000 comparison view using each registered model's existing causal reconstruction/economic contract. Historical simulation only — genuine paper journals and portfolio state are not backdated.</p>\n  <div class="v5-shadow-history-meta"><div class="pill" id="ten-year-model-comparison-status">LOADING RECONSTRUCTIONS</div></div>\n  <div class="model-comparison-wrap">\n    <svg id="ten-year-model-comparison-chart" viewBox="0 0 1100 440" preserveAspectRatio="none" aria-label="Ten-year historical stock model comparison"></svg>\n    <div id="ten-year-model-comparison-tooltip" class="model-comparison-tooltip"></div>\n  </div>\n  <div id="ten-year-model-comparison-summary" class="model-comparison-summary"></div>\n  <p class="muted" style="margin-top:12px">A model line begins only when its exact historical reconstruction is valid. V6/V7 are not fabricated when no promoted executable portfolio exists.</p>\n</section>\n'''
        marker='<section class="card v4-dashboard">'
        if marker not in html: raise RuntimeError('dashboard insertion anchor not found')
        html=html.replace(marker,card+'\n'+marker,1)
        script='<script src="{{ url_for(\'static\', filename=\'js/ten_year_model_comparison_chart.js\') }}"></script>\n'
        html=html.replace('</body>',script+'</body>',1)
    tpl.write_text(html,encoding='utf-8')

    print('[APPLY] ten-year comparison service')
    print('[APPLY] ten-year reconstruction comparison builder')
    print('[APPLY] one interactive multi-model dashboard chart')
    print('[APPLY] API endpoint /api/ten-year-model-comparison')
    print('Historical comparison patch complete.')
    print('No genuine paper state, journal, holdout, or brokerage setting is modified.')

if __name__ == '__main__':
    main()
