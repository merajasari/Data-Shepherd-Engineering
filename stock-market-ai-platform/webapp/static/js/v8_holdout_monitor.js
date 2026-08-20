(() => {
  const root = document.getElementById('v8-holdout-monitor');
  if (!root) return;
  const style = document.createElement('style');
  style.textContent = `
    .v8h-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}
    .v8h-card{padding:12px;border:1px solid rgba(120,155,205,.16);border-radius:12px;background:rgba(7,16,31,.48)}
    .v8h-label{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.v8h-value{font-size:1.05rem;font-weight:700;margin-top:3px}
    .v8h-sha{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;word-break:break-all;color:var(--muted)}
    .v8h-chart{height:280px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.45);overflow:hidden;margin-top:12px}
    .v8h-chart svg{width:100%;height:100%;display:block}.v8h-note{font-size:.78rem;color:var(--muted);margin-top:8px}
    @media(max-width:800px){.v8h-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `; document.head.appendChild(style);
  const fmtPct = v => v == null ? '—' : `${(100*v).toFixed(3)}%`;
  function draw(curve){
    const box=root.querySelector('.v8h-chart'); if(!box)return;
    if(!curve.length){box.innerHTML='<div style="padding:28px;color:var(--muted)">Forward curve will begin after completed holdout cohorts are available.</div>';return;}
    const W=1000,H=280,p=34; const vals=curve.flatMap(x=>[x.strategy_normalized,x.spy_normalized]);
    const lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(1,hi-lo);
    const x=i=>p+(W-2*p)*(i/Math.max(1,curve.length-1)); const y=v=>H-p-(H-2*p)*((v-lo)/span);
    const path=k=>curve.map((d,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(d[k]).toFixed(1)}`).join(' ');
    box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${path('strategy_normalized')}" fill="none" stroke="currentColor" stroke-width="3"/><path d="${path('spy_normalized')}" fill="none" stroke="currentColor" stroke-opacity=".45" stroke-width="2" stroke-dasharray="8 6"/></svg>`;
  }
  async function refresh(){
    try{
      const r=await fetch('/api/v8/holdout',{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`); const d=await r.json();
      root.querySelector('[data-v8h-state]').textContent=d.state;
      root.querySelector('[data-v8h-decisions]').textContent=d.decisions;
      root.querySelector('[data-v8h-exits]').textContent=d.completed_cohorts;
      root.querySelector('[data-v8h-edge]').textContent=fmtPct(d.mean_net_relative_return);
      root.querySelector('[data-v8h-hit]').textContent=fmtPct(d.net_relative_hit_rate);
      root.querySelector('[data-v8h-sha]').textContent=d.frozen_sha256;
      root.querySelector('[data-v8h-start]').textContent=d.holdout_start_utc.replace('T00:00:00+00:00','');
      draw(d.curve||[]);
    }catch(e){root.querySelector('[data-v8h-state]').textContent='MONITOR ERROR'; console.error(e);}
  }
  refresh(); setInterval(refresh,15000);
})();
