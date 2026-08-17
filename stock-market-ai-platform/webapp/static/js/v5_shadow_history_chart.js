(() => {
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
