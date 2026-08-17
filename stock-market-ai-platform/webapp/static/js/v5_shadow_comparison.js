(() => {
  const money = v => `${Number(v) < 0 ? '-' : ''}$${Math.abs(Number(v || 0)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const pct = v => `${Number(v) >= 0 ? '+' : ''}${Number(v || 0).toFixed(2)}%`;
  const tone = v => Number(v) >= 0 ? 'positive' : 'negative';
  const set = (id, text, cls) => { const el=document.getElementById(id); if(!el)return; el.textContent=text; if(cls)el.className=cls; };

  async function load(){
    const status=document.getElementById('v5-shadow-status');
    try{
      const r=await fetch('/api/v5-shadow-comparison',{credentials:'same-origin',cache:'no-store'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      const d=await r.json();
      if(status) status.textContent='PRE-HOLDOUT SHADOW';
      set('v5-shadow-equity',money(d.v5_shadow_equity),tone(d.v5_shadow_pnl));
      set('v5-shadow-return',pct(d.v5_shadow_return_pct),tone(d.v5_shadow_return_pct));
      set('v5-shadow-v4-equity',money(d.v4_normalized_equity),tone(d.v4_since_shadow_return_pct));
      set('v5-shadow-v4-return',pct(d.v4_since_shadow_return_pct),tone(d.v4_since_shadow_return_pct));
      set('v5-shadow-spy-equity',money(d.spy_normalized_equity),tone(d.spy_since_shadow_return_pct));
      set('v5-shadow-spy-return',pct(d.spy_since_shadow_return_pct),tone(d.spy_since_shadow_return_pct));
      set('v5-shadow-vs-v4',`${d.v5_vs_v4_pct_points>=0?'+':''}${Number(d.v5_vs_v4_pct_points).toFixed(3)} pts`,tone(d.v5_vs_v4_pct_points));
      set('v5-shadow-vs-spy',`${d.v5_vs_spy_pct_points>=0?'+':''}${Number(d.v5_vs_spy_pct_points).toFixed(3)} pts`,tone(d.v5_vs_spy_pct_points));
      set('v5-shadow-friction',money(-Math.abs(d.entry_friction)),'negative');
      set('v5-shadow-started',new Date(d.created_at_utc).toLocaleString());
      set('v5-shadow-decision',String(d.decision_timestamp_utc));
      const list=document.getElementById('v5-shadow-holdings');
      if(list){
        list.innerHTML=d.positions.map(p=>`<div class="v5-shadow-row"><div><strong>${p.symbol}</strong><div class="muted">${(p.weight*100).toFixed(0)}% target · ${p.price_source||'price'}</div></div><div class="${tone(p.net_pnl)}"><strong>${money(p.net_pnl)}</strong><div class="muted">${money(p.current_price)}</div></div></div>`).join('');
      }
    }catch(err){
      if(status){status.textContent='SHADOW DATA ERROR';status.className='negative';}
      console.warn('[V5 SHADOW]',err);
    }
  }
  load();
  window.setInterval(load,10000);
})();
