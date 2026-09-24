(() => {
  const money=n=>Number.isFinite(+n)?'$'+(+n).toLocaleString(undefined,{maximumFractionDigits:0}):'—';
  const money2=n=>Number.isFinite(+n)?'$'+(+n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const signedPct=n=>Number.isFinite(+n)?((+n>=0?'+':'')+(+n*100).toFixed(2)+'%'):'—';
  const pctPoints=n=>Number.isFinite(+n)?((+n>=0?'+':'')+(+n*100).toFixed(2)+' pts'):'—';
  const signedMoney2=n=>Number.isFinite(+n)?((+n>=0?'+':'-')+'  const chartStamp=value=>{const d=new Date(value);return Number.isFinite(d.getTime())?d.toLocaleString(undefined,{timeZone:'America/Los_Angeles',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}):'—'};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let marketQuotes={},marketFilter='all',marketSort='change',marketSearch='',marketTimer=null,marketInFlight=false,marketLastSuccess=null,marketFailures=0;

  function sharedV4DrilldownHtml(row){
    const candidate=+row.candidate,benchmark=+row.benchmark;
    const candidateReturn=Number.isFinite(+row.candidate_return)?+row.candidate_return:candidate/100000-1;
    const benchmarkReturn=Number.isFinite(+row.benchmark_return)?+row.benchmark_return:benchmark/100000-1;
    const excessDollars=Number.isFinite(+row.excess_dollars)?+row.excess_dollars:candidate-benchmark;
    const excessPoints=Number.isFinite(+row.excess_return_points)?+row.excess_return_points:candidateReturn-benchmarkReturn;
    const tone=value=>Number(value)<0?'negative':'positive';
    const probability=(label,value,color)=>{
      const n=Number(value),pct=Number.isFinite(n)?Math.max(0,Math.min(100,n*100)):0;
      return \`<div class="chart-drilldown-prob"><div class="chart-drilldown-prob-head"><span>\${esc(label)}</span><b>\${Number.isFinite(n)?pct.toFixed(1)+'%':'—'}</b></div><div class="chart-drilldown-prob-track"><i style="width:\${pct.toFixed(1)}%;background:\${color}"></i></div></div>\`;
    };
    if(row.event_status==='FORWARD_BOUNDARY'){
      return \`<div class="chart-drilldown-summary"><div class="chart-drilldown-kpi"><span>Shared V4</span><strong>\${money2(candidate)}</strong></div><div class="chart-drilldown-kpi"><span>Always-BTC</span><strong>\${money2(benchmark)}</strong></div><div class="chart-drilldown-kpi"><span>Starting basis</span><strong>$100,000.00</strong></div></div><div class="chart-drilldown-foot">This point is the preregistered clean-forward boundary, not a realized trading hour.</div>\`;
    }
    return \`
      <div class="chart-drilldown-summary">
        <div class="chart-drilldown-kpi"><span>Shared V4 equity</span><strong class="\${tone(candidateReturn)}">\${money2(candidate)} · \${signedPct(candidateReturn)}</strong></div>
        <div class="chart-drilldown-kpi"><span>Always-BTC equity</span><strong class="\${tone(benchmarkReturn)}">\${money2(benchmark)} · \${signedPct(benchmarkReturn)}</strong></div>
        <div class="chart-drilldown-kpi"><span>V4 edge vs BTC</span><strong class="\${tone(excessPoints)}">\${signedMoney2(excessDollars)} · \${pctPoints(excessPoints)}</strong></div>
      </div>
      <div class="chart-drilldown-grid">
        <section class="chart-drilldown-group"><h3>Decision + execution</h3>
          <div class="chart-drilldown-row"><span>Decision time</span><b>\${esc(chartStamp(row.decision_timestamp_utc))}</b></div>
          <div class="chart-drilldown-row"><span>Realized through</span><b>\${esc(chartStamp(row.realized_through_utc||row.timestamp))}</b></div>
          <div class="chart-drilldown-row"><span>Model signal</span><b>\${esc(row.raw_predicted_label||'—')}</b></div>
          <div class="chart-drilldown-row"><span>Executed sleeve</span><b>\${esc(row.executed_label_after||'—')}</b></div>
          <div class="chart-drilldown-row"><span>Previous sleeve</span><b>\${esc(row.executed_label_before||'—')}</b></div>
          <div class="chart-drilldown-row"><span>Sleeve switch</span><b>\${row.sleeve_switch?'YES':'NO'}</b></div>
          <div class="chart-drilldown-row"><span>Status</span><b>\${esc(row.event_status||'REALIZED')}</b></div>
        </section>
        <section class="chart-drilldown-group"><h3>Hourly outcome</h3>
          <div class="chart-drilldown-row"><span>Selected sleeve net</span><b class="\${tone(row.net_selected_return_1h)}">\${signedPct(row.net_selected_return_1h)}</b></div>
          <div class="chart-drilldown-row"><span>Selected sleeve gross</span><b class="\${tone(row.gross_selected_return_1h)}">\${signedPct(row.gross_selected_return_1h)}</b></div>
          <div class="chart-drilldown-row"><span>BTC 1h return</span><b class="\${tone(row.btc_realized_return_1h)}">\${signedPct(row.btc_realized_return_1h)}</b></div>
          <div class="chart-drilldown-row"><span>ALT 1h return</span><b class="\${tone(row.alt_realized_return_1h)}">\${signedPct(row.alt_realized_return_1h)}</b></div>
          <div class="chart-drilldown-row"><span>Modeled transaction cost</span><b>\${signedPct(-Math.abs(Number(row.transaction_cost)||0))}</b></div>
          <div class="chart-drilldown-row"><span>Cost assumption</span><b>\${Number.isFinite(+row.cost_bps_assumption)?(+row.cost_bps_assumption).toFixed(0)+' bps':'—'}</b></div>
        </section>
        <section class="chart-drilldown-group"><h3>Risk + relative performance</h3>
          <div class="chart-drilldown-row"><span>V4 drawdown</span><b class="\${tone(row.candidate_drawdown)}">\${signedPct(row.candidate_drawdown)}</b></div>
          <div class="chart-drilldown-row"><span>BTC drawdown</span><b class="\${tone(row.benchmark_drawdown)}">\${signedPct(row.benchmark_drawdown)}</b></div>
          <div class="chart-drilldown-row"><span>Dollar edge vs BTC</span><b class="\${tone(excessDollars)}">\${signedMoney2(excessDollars)}</b></div>
          <div class="chart-drilldown-row"><span>Return edge vs BTC</span><b class="\${tone(excessPoints)}">\${pctPoints(excessPoints)}</b></div>
        </section>
        <section class="chart-drilldown-group"><h3>Model probabilities</h3>
          \${probability('BTC',row.prob_btc,'#4d8cff')}
          \${probability('ALT',row.prob_alt,'#39e3a1')}
          \${probability('CASH',row.prob_cash,'#efc56b')}
        </section>
      </div>
      <div class="chart-drilldown-foot">Read-only view of one genuine post-boundary hourly realization. Opening this panel does not invoke the model, alter the journal, or place an order.</div>\`;
  }

  function openSharedV4Drilldown(row){
    const modal=document.getElementById('shared-v4-drilldown');
    if(!modal||!row)return;
    const title=modal.querySelector('[data-shared-v4-drilldown-title]');
    const subtitle=modal.querySelector('[data-shared-v4-drilldown-subtitle]');
    const content=modal.querySelector('[data-shared-v4-drilldown-content]');
    const boundary=row.event_status==='FORWARD_BOUNDARY';
    if(title)title.textContent=boundary?'Clean-forward boundary':chartStamp(row.realized_through_utc||row.timestamp);
    if(subtitle)subtitle.textContent=boundary?'Preregistered starting point':'Hourly realization · '+String(row.event_status||'REALIZED')+' · click outside or press Esc to close';
    if(content)content.innerHTML=sharedV4DrilldownHtml(row);
    modal.hidden=false;modal.setAttribute('aria-hidden','false');document.body.classList.add('chart-drilldown-open');
    window.requestAnimationFrame(()=>modal.querySelector('.chart-drilldown-close')?.focus());
  }

  function closeSharedV4Drilldown(){
    const modal=document.getElementById('shared-v4-drilldown');if(!modal||modal.hidden)return;
    modal.hidden=true;modal.setAttribute('aria-hidden','true');document.body.classList.remove('chart-drilldown-open');
  }

  function setupSharedV4Drilldown(){
    const modal=document.getElementById('shared-v4-drilldown');if(!modal)return;
    modal.addEventListener('click',event=>{if(event.target.closest('[data-shared-v4-close]'))closeSharedV4Drilldown()});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!modal.hidden)closeSharedV4Drilldown()});
  }

  function setupTabs(){const tabs=[...document.querySelectorAll('[data-crypto-tab]')],panels=[...document.querySelectorAll('[data-crypto-panel]')];const show=id=>{tabs.forEach(t=>{const on=t.dataset.cryptoTab===id;t.classList.toggle('active',on);t.setAttribute('aria-selected',on);t.tabIndex=on?0:-1});panels.forEach(p=>p.hidden=p.dataset.cryptoPanel!==id);history.replaceState(null,'',id==='overview'?location.pathname:`#${id}`)};tabs.forEach((t,i)=>{t.onclick=()=>show(t.dataset.cryptoTab);t.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].focus();show(tabs[n].dataset.cryptoTab)}});const initial=location.hash.slice(1);show(tabs.some(t=>t.dataset.cryptoTab===initial)?initial:'overview')}

  function forwardLineChart(id,rows,definitions,{percent=false,currency=false,height=430,interactive=false,hourlySlots=false,drilldown=false}={}){
    const svg=document.getElementById(id);if(!svg)return;svg.innerHTML='';
    const data=(rows||[]).map(row=>({...row,_t:Date.parse(row.timestamp)})).filter(row=>Number.isFinite(row._t));
    const defs=definitions.filter(def=>data.some(row=>Number.isFinite(+row[def.key])));
    if(data.length<2||!defs.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">Forward observations will appear here as they complete</text>';return}
    const W=1100,H=height,pad={l:88,r:40,t:38,b:hourlySlots?72:48},times=data.map(row=>row._t),minT=Math.min(...times),maxT=Math.max(...times);
    const values=data.flatMap(row=>defs.map(def=>+row[def.key])).filter(Number.isFinite);let minV=Math.min(...values),maxV=Math.max(...values);
    if(percent){minV=Math.min(minV,0);maxV=Math.max(maxV,0)}else{const span=Math.max(1,maxV-minV);minV-=span*.12;maxV+=span*.12}
    const ns='http://www.w3.org/2000/svg',add=(tag,attrs,parent=svg)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));parent.appendChild(el);return el};
    const x=time=>pad.l+(W-pad.l-pad.r)*(time-minT)/Math.max(1,maxT-minT),y=value=>pad.t+(H-pad.t-pad.b)*(1-(value-minV)/Math.max(1e-9,maxV-minV));
    for(let i=0;i<5;i++){const value=minV+(maxV-minV)*i/4;add('line',{x1:pad.l,x2:W-pad.r,y1:y(value),y2:y(value),stroke:'rgba(145,166,194,.15)'});const label=add('text',{x:pad.l-10,y:y(value)+4,fill:'#91a6c2','text-anchor':'end','font-size':12});label.textContent=currency?money(value):percent?`${(value*100).toFixed(1)}%`:value.toFixed(2)}
    const shortWindow=maxT-minT<=3*864e5;
    if(hourlySlots&&maxT-minT<=36*3600e3){
      const firstHour=Math.ceil(minT/3600e3)*3600e3;
      const hourCount=Math.max(1,Math.floor((maxT-firstHour)/3600e3)+1);
      const labelEvery=hourCount>18?2:1;
      for(let time=firstHour,index=0;time<=maxT;time+=3600e3,index++){
        const xx=x(time);
        add('line',{x1:xx,x2:xx,y1:pad.t,y2:H-pad.b,stroke:'rgba(145,166,194,.08)','stroke-width':1});
        add('line',{x1:xx,x2:xx,y1:H-pad.b,y2:H-pad.b+6,stroke:'rgba(145,166,194,.45)','stroke-width':1});
        if(index%labelEvery===0){
          const label=add('text',{x:xx,y:H-29,fill:'#91a6c2','text-anchor':'middle','font-size':10.5});
          label.textContent=new Date(time).toLocaleTimeString(undefined,{timeZone:'America/Los_Angeles',hour:'numeric'});
        }
      }
      const axisTitle=add('text',{x:(pad.l+W-pad.r)/2,y:H-8,fill:'#91a6c2','text-anchor':'middle','font-size':10.5,'font-weight':800,'letter-spacing':'.08em'});
      axisTitle.textContent='1-HOUR SLOTS · PACIFIC TIME';
    }else{
      for(let i=0;i<5;i++){const time=minT+(maxT-minT)*i/4;const label=add('text',{x:x(time),y:H-16,fill:'#91a6c2','text-anchor':i===0?'start':i===4?'end':'middle','font-size':12});label.textContent=new Date(time).toLocaleString(undefined,shortWindow?{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric'}:{timeZone:'America/Los_Angeles',month:'short',day:'numeric'})}
    }
    defs.forEach((def,index)=>{
      const points=data.filter(row=>Number.isFinite(+row[def.key]));
      add('polyline',{points:points.map(row=>\`\${x(row._t)},\${y(+row[def.key])}\`).join(' '),fill:'none',stroke:def.color,'stroke-width':3.5,'stroke-linejoin':'round','stroke-linecap':'round','data-forward-series':def.key});
      points.forEach(row=>{
        const attrs={cx:x(row._t),cy:y(+row[def.key]),r:drilldown?4.5:3.5,fill:def.color,stroke:'#07101f','stroke-width':2,opacity:.95};
        if(drilldown){attrs['data-forward-point-index']=String(data.indexOf(row));attrs['data-forward-point-series']=def.key;attrs.tabindex='0';attrs.role='button';attrs['aria-label']=\`\${def.label} · \${chartStamp(row.timestamp)} · click to drill in\`;attrs.style='cursor:pointer'}
        add('circle',attrs);
      });
      const legendX=pad.l+index*190;add('line',{x1:legendX,x2:legendX+24,y1:17,y2:17,stroke:def.color,'stroke-width':4});const label=add('text',{x:legendX+31,y:21,fill:'#dfeaff','font-size':12,'font-weight':800});label.textContent=def.label;
    });

    if(interactive){
      const tip=document.getElementById(`${id}-tip`);
      if(!tip)return;
      const cross=add('line',{x1:0,x2:0,y1:pad.t,y2:H-pad.b,stroke:'rgba(242,246,255,.7)','stroke-width':1.2,'stroke-dasharray':'5 4',visibility:'hidden'});
      const focusDots=defs.map(def=>add('circle',{cx:0,cy:0,r:6.5,fill:def.color,stroke:'#07101f','stroke-width':3,visibility:'hidden','pointer-events':'none'}));
      let pinned=false;
      let activeRow=null;

      const tooltipHtml=row=>{
        const candidate=+row.candidate,benchmark=+row.benchmark;
        const candidateReturn=Number.isFinite(+row.candidate_return)?+row.candidate_return:candidate/100000-1;
        const benchmarkReturn=Number.isFinite(+row.benchmark_return)?+row.benchmark_return:benchmark/100000-1;
        const excessDollars=Number.isFinite(+row.excess_dollars)?+row.excess_dollars:candidate-benchmark;
        const excessPoints=Number.isFinite(+row.excess_return_points)?+row.excess_return_points:candidateReturn-benchmarkReturn;
        const boundary=row.event_status==='FORWARD_BOUNDARY';
        if(boundary)return `<strong>${esc(chartStamp(row.timestamp))} · FORWARD BOUNDARY</strong><div><span>Shared V4</span><b>${money2(candidate)}</b></div><div><span>Always-BTC</span><b>${money2(benchmark)}</b></div><div><span>Starting basis</span><b>$100,000.00</b></div>`;
        return `<strong>${esc(chartStamp(row.realized_through_utc||row.timestamp))} · ${esc(row.event_status||'REALIZED')}</strong>
          <div><span>Decision</span><b>${esc(chartStamp(row.decision_timestamp_utc))}</b></div>
          <div><span>Shared V4 equity</span><b>${money2(candidate)} · ${signedPct(candidateReturn)}</b></div>
          <div><span>Always-BTC equity</span><b>${money2(benchmark)} · ${signedPct(benchmarkReturn)}</b></div>
          <div><span>V4 edge vs BTC</span><b>${excessDollars>=0?'+':''}${money2(excessDollars)} · ${pctPoints(excessPoints)}</b></div>
          <div><span>Executed sleeve</span><b>${esc(row.executed_label_after||'—')}</b></div>
          <div><span>Model signal</span><b>${esc(row.raw_predicted_label||'—')}</b></div>
          <div><span>Sleeve switch</span><b>${row.sleeve_switch?'YES':'NO'}</b></div>
          <div><span>1h selected net</span><b>${signedPct(row.net_selected_return_1h)}</b></div>
          <div><span>BTC 1h</span><b>${signedPct(row.btc_realized_return_1h)}</b></div>
          <div><span>ALT 1h</span><b>${signedPct(row.alt_realized_return_1h)}</b></div>
          <div><span>Modeled cost</span><b>${signedPct(-Math.abs(Number(row.transaction_cost)||0))} · ${Number.isFinite(+row.cost_bps_assumption)?(+row.cost_bps_assumption).toFixed(0)+' bps':'—'}</b></div>
          <div><span>V4 drawdown</span><b>${signedPct(row.candidate_drawdown)}</b></div>
          <div><span>BTC drawdown</span><b>${signedPct(row.benchmark_drawdown)}</b></div>
          <div><span>Prob BTC / ALT / CASH</span><b>${Number.isFinite(+row.prob_btc)?(+row.prob_btc*100).toFixed(1):'—'}% / ${Number.isFinite(+row.prob_alt)?(+row.prob_alt*100).toFixed(1):'—'}% / ${Number.isFinite(+row.prob_cash)?(+row.prob_cash*100).toFixed(1):'—'}%</b></div>
          <small style="display:block;margin-top:7px;color:#91a6c2">${pinned?'PINNED · click chart background again or press Esc to release':drilldown?'Hover another hour · click a dot to drill in':'Hover for another hour · click to pin'}</small>`;
      };

      const show=(row,event)=>{
        activeRow=row;
        const xx=x(row._t);
        cross.setAttribute('x1',xx);cross.setAttribute('x2',xx);cross.setAttribute('visibility','visible');
        defs.forEach((def,index)=>{
          const value=+row[def.key],dot=focusDots[index];
          if(Number.isFinite(value)){dot.setAttribute('cx',xx);dot.setAttribute('cy',y(value));dot.setAttribute('visibility','visible')}else dot.setAttribute('visibility','hidden');
        });
        tip.innerHTML=tooltipHtml(row);
        tip.classList.add('visible');
        const rect=svg.getBoundingClientRect();
        const left=Math.max(150,Math.min(rect.width-150,xx/W*rect.width));
        const yValues=defs.map(def=>+row[def.key]).filter(Number.isFinite);
        const yy=yValues.length?Math.min(...yValues.map(y)):pad.t;
        tip.style.left=`${left}px`;
        tip.style.top=`${Math.max(120,Math.min(rect.height-10,yy/H*rect.height))}px`;
      };
      const hide=()=>{cross.setAttribute('visibility','hidden');focusDots.forEach(dot=>dot.setAttribute('visibility','hidden'));tip.classList.remove('visible');activeRow=null};

      svg.addEventListener('pointermove',event=>{
        if(pinned)return;
        const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)/rect.width*W;
        if(px<pad.l||px>W-pad.r){hide();return}
        const target=minT+(px-pad.l)/(W-pad.l-pad.r)*(maxT-minT);
        const row=data.reduce((best,item)=>Math.abs(item._t-target)<Math.abs(best._t-target)?item:best,data[0]);
        show(row,event);
      });
      svg.addEventListener('pointerleave',()=>{if(!pinned)hide()});
      svg.addEventListener('click',event=>{
        const point=drilldown?event.target.closest?.('[data-forward-point-index]'):null;
        if(point){
          const row=data[Number(point.getAttribute('data-forward-point-index'))];
          if(row){pinned=false;show(row,event);openSharedV4Drilldown(row)}
          return;
        }
        if(pinned){pinned=false;if(activeRow)show(activeRow,event);else hide();return}
        const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)/rect.width*W;
        if(px<pad.l||px>W-pad.r)return;
        const target=minT+(px-pad.l)/(W-pad.l-pad.r)*(maxT-minT);
        const row=data.reduce((best,item)=>Math.abs(item._t-target)<Math.abs(best._t-target)?item:best,data[0]);
        pinned=true;show(row,event);
      });
      svg.addEventListener('keydown',event=>{
        if(!drilldown||!['Enter',' '].includes(event.key))return;
        const point=event.target.closest?.('[data-forward-point-index]');if(!point)return;
        event.preventDefault();
        const row=data[Number(point.getAttribute('data-forward-point-index'))];
        if(row){pinned=false;show(row,event);openSharedV4Drilldown(row)}
      });
      document.addEventListener('keydown',event=>{if(event.key==='Escape'&&pinned){pinned=false;hide()}});
    }
  }

  function forwardBarChart(id,rows,definitions){
    const svg=document.getElementById(id);if(!svg)return;svg.innerHTML='';const data=(rows||[]).map(row=>({...row,_t:Date.parse(row.timestamp)})).filter(row=>Number.isFinite(row._t));
    if(!data.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">Completed return periods will appear here</text>';return}
    const W=1100,H=260,pad={l:76,r:30,t:36,b:46},values=data.flatMap(row=>definitions.map(def=>+row[def.key])).filter(Number.isFinite),limit=Math.max(.001,...values.map(Math.abs));
    const ns='http://www.w3.org/2000/svg',add=(tag,attrs)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));svg.appendChild(el);return el},y=value=>pad.t+(H-pad.t-pad.b)*(1-(value+limit)/(2*limit)),group=(W-pad.l-pad.r)/data.length,bar=Math.max(2,Math.min(22,group/(definitions.length+1)));
    add('line',{x1:pad.l,x2:W-pad.r,y1:y(0),y2:y(0),stroke:'rgba(242,246,255,.5)','stroke-width':1.5});
    data.forEach((row,i)=>definitions.forEach((def,j)=>{const value=+row[def.key];if(!Number.isFinite(value))return;const x=pad.l+i*group+(group-definitions.length*bar)/2+j*bar;add('rect',{x,y:Math.min(y(value),y(0)),width:Math.max(1,bar-2),height:Math.max(1,Math.abs(y(value)-y(0))),rx:2,fill:def.color,opacity:.9})}));
    definitions.forEach((def,index)=>{const x=pad.l+index*180;add('rect',{x,y:10,width:13,height:13,rx:3,fill:def.color});const label=add('text',{x:x+20,y:21,fill:'#dfeaff','font-size':12,'font-weight':800});label.textContent=def.label});
    const top=add('text',{x:pad.l-8,y:y(limit)+4,fill:'#91a6c2','text-anchor':'end','font-size':11});top.textContent=`+${(limit*100).toFixed(1)}%`;const bottom=add('text',{x:pad.l-8,y:y(-limit)+4,fill:'#91a6c2','text-anchor':'end','font-size':11});bottom.textContent=`-${(limit*100).toFixed(1)}%`;
  }

  function renderForwardCharts(){
    const source=document.getElementById('crypto-forward-chart-data');if(!source)return;let data;try{data=JSON.parse(source.textContent)}catch{return}
    const shared=data.shared_v2||{},v5=data.v5||{};
    forwardLineChart('shared-v2-equity',shared.chart_points,[{key:'candidate',label:'Shared V4',color:'#39e3a1'},{key:'benchmark',label:'Always BTC',color:'#4d8cff'}],{currency:true,interactive:true,hourlySlots:true,drilldown:true});
    forwardLineChart('shared-v2-drawdown',shared.chart_points,[{key:'candidate_drawdown',label:'Shared V4',color:'#39e3a1'},{key:'benchmark_drawdown',label:'Always BTC',color:'#4d8cff'}],{percent:true,height:260});
    forwardBarChart('shared-v2-returns',shared.return_points,[{key:'net_return',label:'Selected sleeve',color:'#39e3a1'},{key:'btc_return',label:'BTC',color:'#4d8cff'}]);
    forwardLineChart('shared-v2-probabilities',shared.probability_points,[{key:'btc',label:'BTC probability',color:'#4d8cff'},{key:'alt',label:'ALT probability',color:'#39e3a1'},{key:'cash',label:'CASH probability',color:'#efc56b'}],{percent:true,height:360});
    forwardLineChart('v5-forward-equity',v5.chart_points,[{key:'candidate',label:'Crypto V5',color:'#36d8ff'}],{currency:true});
    forwardLineChart('v5-forward-drawdown',v5.chart_points,[{key:'candidate_drawdown',label:'Crypto V5',color:'#ff6680'}],{percent:true,height:260});
    forwardBarChart('v5-forward-returns',v5.return_points,[{key:'net_return',label:'Net return',color:'#36d8ff'},{key:'gross_return',label:'Gross return',color:'#9b65ff'}]);
  }

  const marketNames={'AAVE-USD':'Aave','ADA-USD':'Cardano','ARB-USD':'Arbitrum','ATOM-USD':'Cosmos','AVAX-USD':'Avalanche','BCH-USD':'Bitcoin Cash','BTC-USD':'Bitcoin','DOGE-USD':'Dogecoin','DOT-USD':'Polkadot','ETC-USD':'Ethereum Classic','ETH-USD':'Ethereum','FIL-USD':'Filecoin','HBAR-USD':'Hedera','ICP-USD':'Internet Computer','INJ-USD':'Injective','LINK-USD':'Chainlink','LTC-USD':'Litecoin','NEAR-USD':'NEAR Protocol','OP-USD':'Optimism','SHIB-USD':'Shiba Inu','SOL-USD':'Solana','SUI-USD':'Sui','UNI-USD':'Uniswap','XLM-USD':'Stellar','XRP-USD':'XRP'};
  const liveMoney=value=>{const n=Number(value);if(!Number.isFinite(n))return'—';const digits=Math.abs(n)>=1000?2:Math.abs(n)>=1?4:8;return'$'+n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:digits})};
  const livePct=value=>{const n=Number(value);if(!Number.isFinite(n))return'—';return`${n>=0?'+':''}${n.toFixed(2)}%`};
  const changeOf=quote=>{const n=Number(quote?.price_percent_chg_24_h);return Number.isFinite(n)?n:null};

  function marketRows(){
    const btcChange=changeOf(marketQuotes['BTC-USD']);
    let rows=Object.entries(marketQuotes).map(([symbol,quote])=>({symbol,quote,price:Number(quote?.price),change:changeOf(quote),relative:Number.isFinite(btcChange)&&Number.isFinite(changeOf(quote))?changeOf(quote)-btcChange:null})).filter(row=>Number.isFinite(row.price)&&Number.isFinite(row.change));
    const query=marketSearch.trim().toLowerCase();
    if(query)rows=rows.filter(row=>row.symbol.toLowerCase().includes(query)||(marketNames[row.symbol]||'').toLowerCase().includes(query));
    if(marketFilter==='gainers')rows=rows.filter(row=>row.change>0);
    if(marketFilter==='losers')rows=rows.filter(row=>row.change<0);
    if(marketFilter==='extreme')rows=rows.filter(row=>Math.abs(row.change)>=5);
    const sorters={symbol:(a,b)=>a.symbol.localeCompare(b.symbol),price:(a,b)=>b.price-a.price,change:(a,b)=>b.change-a.change,relative:(a,b)=>b.relative-a.relative};
    return rows.sort(sorters[marketSort]||sorters.change);
  }

  function renderMarketBoard(updatedAt){
    const all=Object.entries(marketQuotes).map(([symbol,quote])=>({symbol,price:Number(quote?.price),change:changeOf(quote)})).filter(row=>Number.isFinite(row.price)&&Number.isFinite(row.change)).sort((a,b)=>b.change-a.change);
    if(!all.length)return;
    const btc=all.find(row=>row.symbol==='BTC-USD'),up=all.filter(row=>row.change>0).length,down=all.filter(row=>row.change<0).length;
    const ordered=[...all].map(row=>row.change).sort((a,b)=>a-b),mid=Math.floor(ordered.length/2),median=ordered.length%2?ordered[mid]:(ordered[mid-1]+ordered[mid])/2;
    const extreme=all.filter(row=>Math.abs(row.change)>=5).length,leader=all[0],laggard=all[all.length-1],maxAbs=Math.max(0.01,...all.map(row=>Math.abs(row.change)));
    const set=(id,text,cls='')=>{const node=document.getElementById(id);if(node){node.textContent=text;node.className=cls;}};
    set('crypto-market-breadth',`${up} UP · ${down} DOWN`,up>=down?'positive':'negative');
    set('crypto-market-breadth-detail',`${Math.round(up/all.length*100)}% of tracked assets are positive`);
    set('crypto-market-median',livePct(median),median>=0?'positive':'negative');
    set('crypto-market-extremes',`${leader.symbol.replace('-USD','')} / ${laggard.symbol.replace('-USD','')}`);
    set('crypto-market-extremes-detail',`${livePct(leader.change)} · ${livePct(laggard.change)}`);
    set('crypto-market-extreme-count',`${extreme} / ${all.length}`,extreme?'gold':'');
    set('crypto-market-btc-change',btc?livePct(btc.change):'—',btc?.change>=0?'positive':'negative');
    set('crypto-market-btc-price',btc?liveMoney(btc.price):'Price unavailable');
    const stamp=document.getElementById('crypto-live-ticker-stamp');if(stamp){stamp.textContent=`LIVE CACHE · ${updatedAt||'CURRENT'}`;stamp.className='mode';}
    const detail=document.getElementById('crypto-live-ticker-detail');if(detail)detail.textContent=`Auto-refresh · ${new Date().toLocaleTimeString()} · ${all.length} Coinbase USD markets`;
    const rows=marketRows(),root=document.getElementById('crypto-market-board');if(!root)return;
    root.innerHTML=rows.map(row=>`<tr><td><div class="market-asset"><span class="market-coin">${esc(row.symbol.replace('-USD','').slice(0,4))}</span><div><strong>${esc(row.symbol)}</strong><small>${esc(marketNames[row.symbol]||'')}</small></div></div></td><td><strong>${liveMoney(row.price)}</strong></td><td class="market-change-cell ${row.change>=0?'positive':'negative'}"><strong>${livePct(row.change)}</strong><small>${row.change>=0?'GAINING':'DECLINING'}</small></td><td class="${row.relative>=0?'positive':'negative'}">${livePct(row.relative)}</td><td><div class="market-intensity"><span>${Math.abs(row.change).toFixed(1)}%</span><span class="market-intensity-track"><i class="${row.change<0?'down':''}" style="width:${Math.max(2,Math.abs(row.change)/maxAbs*100).toFixed(1)}%"></i></span></div></td></tr>`).join('')||'<tr><td colspan="5">No assets match this search and filter.</td></tr>';
    document.querySelectorAll('[data-market-filter]').forEach(button=>button.classList.toggle('active',button.dataset.marketFilter===marketFilter));
    document.querySelectorAll('[data-market-sort]').forEach(button=>button.classList.toggle('active',button.dataset.marketSort===marketSort));
  }

  function scheduleMarketRefresh(delay=2000){if(marketTimer)window.clearTimeout(marketTimer);marketTimer=window.setTimeout(refreshMarket,delay)}
  async function refreshMarket(){
    if(!document.getElementById('crypto-market-board'))return;
    if(document.hidden){scheduleMarketRefresh();return}
    if(marketInFlight)return;marketInFlight=true;
    try{const response=await fetch('/api/crypto-live',{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();marketQuotes=data.quotes||{};if(!Object.keys(marketQuotes).length)throw new Error(data.error||'No live quotes available');marketLastSuccess=new Date();marketFailures=0;renderMarketBoard(data.updated_at)}catch(error){marketFailures+=1;const stamp=document.getElementById('crypto-live-ticker-stamp');if(stamp){stamp.textContent=marketLastSuccess?'STALE · RETRYING':'UNAVAILABLE · RETRYING';stamp.className='mode negative'}const detail=document.getElementById('crypto-live-ticker-detail');if(detail)detail.textContent=`${error.message} · retry ${marketFailures} · last success ${marketLastSuccess?.toLocaleTimeString()||'none'}`;}finally{marketInFlight=false;scheduleMarketRefresh()}
  }

  function initMarketBoard(){
    if(!document.getElementById('crypto-market-board'))return;
    document.getElementById('crypto-market-search')?.addEventListener('input',event=>{marketSearch=event.target.value;renderMarketBoard()});
    document.querySelectorAll('[data-market-filter]').forEach(button=>button.addEventListener('click',()=>{marketFilter=button.dataset.marketFilter;renderMarketBoard()}));
    document.querySelectorAll('[data-market-sort]').forEach(button=>button.addEventListener('click',()=>{marketSort=button.dataset.marketSort;renderMarketBoard()}));
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshMarket()});
    refreshMarket();
  }
  function initPaperCountdowns(){
    const formatDuration=ms=>{const total=Math.max(0,Math.floor(ms/1000)),hours=Math.floor(total/3600),minutes=Math.floor((total%3600)/60);return hours?hours+'h '+minutes+'m':minutes+'m'};
    const formatPacific=date=>new Intl.DateTimeFormat(undefined,{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(date);
    const update=()=>document.querySelectorAll('[data-paper-countdown]').forEach(node=>{const target=new Date(node.dataset.target),label=node.dataset.label,cadence=node.dataset.cadence,span=node.querySelector('span');if(!span||!Number.isFinite(target.getTime()))return;const now=new Date();if(now<target){span.textContent=label+' begins in '+formatDuration(target-now)+' · '+formatPacific(target);return}if(cadence==='hourly'){const next=new Date(now);next.setUTCMinutes(0,0,0);next.setUTCHours(next.getUTCHours()+1);span.textContent='PAPER TRADING ACTIVE · next hourly boundary '+formatPacific(next)}else{span.textContent='CLEAN WINDOW OPEN · first/next daily decision at 5:00 PM Pacific'}});
    update();window.setInterval(update,30000);
  }

  setupTabs();setupSharedV4Drilldown();renderForwardCharts();initMarketBoard();initPaperCountdowns();
})();
+Math.abs(+n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})):'—';
  const chartStamp=value=>{const d=new Date(value);return Number.isFinite(d.getTime())?d.toLocaleString(undefined,{timeZone:'America/Los_Angeles',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}):'—'};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let marketQuotes={},marketFilter='all',marketSort='change',marketSearch='',marketTimer=null,marketInFlight=false,marketLastSuccess=null,marketFailures=0;

  function setupTabs(){const tabs=[...document.querySelectorAll('[data-crypto-tab]')],panels=[...document.querySelectorAll('[data-crypto-panel]')];const show=id=>{tabs.forEach(t=>{const on=t.dataset.cryptoTab===id;t.classList.toggle('active',on);t.setAttribute('aria-selected',on);t.tabIndex=on?0:-1});panels.forEach(p=>p.hidden=p.dataset.cryptoPanel!==id);history.replaceState(null,'',id==='overview'?location.pathname:`#${id}`)};tabs.forEach((t,i)=>{t.onclick=()=>show(t.dataset.cryptoTab);t.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].focus();show(tabs[n].dataset.cryptoTab)}});const initial=location.hash.slice(1);show(tabs.some(t=>t.dataset.cryptoTab===initial)?initial:'overview')}

  function forwardLineChart(id,rows,definitions,{percent=false,currency=false,height=430,interactive=false,hourlySlots=false}={}){
    const svg=document.getElementById(id);if(!svg)return;svg.innerHTML='';
    const data=(rows||[]).map(row=>({...row,_t:Date.parse(row.timestamp)})).filter(row=>Number.isFinite(row._t));
    const defs=definitions.filter(def=>data.some(row=>Number.isFinite(+row[def.key])));
    if(data.length<2||!defs.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">Forward observations will appear here as they complete</text>';return}
    const W=1100,H=height,pad={l:88,r:40,t:38,b:hourlySlots?72:48},times=data.map(row=>row._t),minT=Math.min(...times),maxT=Math.max(...times);
    const values=data.flatMap(row=>defs.map(def=>+row[def.key])).filter(Number.isFinite);let minV=Math.min(...values),maxV=Math.max(...values);
    if(percent){minV=Math.min(minV,0);maxV=Math.max(maxV,0)}else{const span=Math.max(1,maxV-minV);minV-=span*.12;maxV+=span*.12}
    const ns='http://www.w3.org/2000/svg',add=(tag,attrs,parent=svg)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));parent.appendChild(el);return el};
    const x=time=>pad.l+(W-pad.l-pad.r)*(time-minT)/Math.max(1,maxT-minT),y=value=>pad.t+(H-pad.t-pad.b)*(1-(value-minV)/Math.max(1e-9,maxV-minV));
    for(let i=0;i<5;i++){const value=minV+(maxV-minV)*i/4;add('line',{x1:pad.l,x2:W-pad.r,y1:y(value),y2:y(value),stroke:'rgba(145,166,194,.15)'});const label=add('text',{x:pad.l-10,y:y(value)+4,fill:'#91a6c2','text-anchor':'end','font-size':12});label.textContent=currency?money(value):percent?`${(value*100).toFixed(1)}%`:value.toFixed(2)}
    const shortWindow=maxT-minT<=3*864e5;
    if(hourlySlots&&maxT-minT<=36*3600e3){
      const firstHour=Math.ceil(minT/3600e3)*3600e3;
      const hourCount=Math.max(1,Math.floor((maxT-firstHour)/3600e3)+1);
      const labelEvery=hourCount>18?2:1;
      for(let time=firstHour,index=0;time<=maxT;time+=3600e3,index++){
        const xx=x(time);
        add('line',{x1:xx,x2:xx,y1:pad.t,y2:H-pad.b,stroke:'rgba(145,166,194,.08)','stroke-width':1});
        add('line',{x1:xx,x2:xx,y1:H-pad.b,y2:H-pad.b+6,stroke:'rgba(145,166,194,.45)','stroke-width':1});
        if(index%labelEvery===0){
          const label=add('text',{x:xx,y:H-29,fill:'#91a6c2','text-anchor':'middle','font-size':10.5});
          label.textContent=new Date(time).toLocaleTimeString(undefined,{timeZone:'America/Los_Angeles',hour:'numeric'});
        }
      }
      const axisTitle=add('text',{x:(pad.l+W-pad.r)/2,y:H-8,fill:'#91a6c2','text-anchor':'middle','font-size':10.5,'font-weight':800,'letter-spacing':'.08em'});
      axisTitle.textContent='1-HOUR SLOTS · PACIFIC TIME';
    }else{
      for(let i=0;i<5;i++){const time=minT+(maxT-minT)*i/4;const label=add('text',{x:x(time),y:H-16,fill:'#91a6c2','text-anchor':i===0?'start':i===4?'end':'middle','font-size':12});label.textContent=new Date(time).toLocaleString(undefined,shortWindow?{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric'}:{timeZone:'America/Los_Angeles',month:'short',day:'numeric'})}
    }
    defs.forEach((def,index)=>{const points=data.filter(row=>Number.isFinite(+row[def.key]));add('polyline',{points:points.map(row=>`${x(row._t)},${y(+row[def.key])}`).join(' '),fill:'none',stroke:def.color,'stroke-width':3.5,'stroke-linejoin':'round','stroke-linecap':'round','data-forward-series':def.key});points.forEach(row=>add('circle',{cx:x(row._t),cy:y(+row[def.key]),r:3.5,fill:def.color,stroke:'#07101f','stroke-width':2,opacity:.95}));const legendX=pad.l+index*190;add('line',{x1:legendX,x2:legendX+24,y1:17,y2:17,stroke:def.color,'stroke-width':4});const label=add('text',{x:legendX+31,y:21,fill:'#dfeaff','font-size':12,'font-weight':800});label.textContent=def.label});

    if(interactive){
      const tip=document.getElementById(`${id}-tip`);
      if(!tip)return;
      const cross=add('line',{x1:0,x2:0,y1:pad.t,y2:H-pad.b,stroke:'rgba(242,246,255,.7)','stroke-width':1.2,'stroke-dasharray':'5 4',visibility:'hidden'});
      const focusDots=defs.map(def=>add('circle',{cx:0,cy:0,r:6.5,fill:def.color,stroke:'#07101f','stroke-width':3,visibility:'hidden'}));
      let pinned=false;
      let activeRow=null;

      const tooltipHtml=row=>{
        const candidate=+row.candidate,benchmark=+row.benchmark;
        const candidateReturn=Number.isFinite(+row.candidate_return)?+row.candidate_return:candidate/100000-1;
        const benchmarkReturn=Number.isFinite(+row.benchmark_return)?+row.benchmark_return:benchmark/100000-1;
        const excessDollars=Number.isFinite(+row.excess_dollars)?+row.excess_dollars:candidate-benchmark;
        const excessPoints=Number.isFinite(+row.excess_return_points)?+row.excess_return_points:candidateReturn-benchmarkReturn;
        const boundary=row.event_status==='FORWARD_BOUNDARY';
        if(boundary)return `<strong>${esc(chartStamp(row.timestamp))} · FORWARD BOUNDARY</strong><div><span>Shared V4</span><b>${money2(candidate)}</b></div><div><span>Always-BTC</span><b>${money2(benchmark)}</b></div><div><span>Starting basis</span><b>$100,000.00</b></div>`;
        return `<strong>${esc(chartStamp(row.realized_through_utc||row.timestamp))} · ${esc(row.event_status||'REALIZED')}</strong>
          <div><span>Decision</span><b>${esc(chartStamp(row.decision_timestamp_utc))}</b></div>
          <div><span>Shared V4 equity</span><b>${money2(candidate)} · ${signedPct(candidateReturn)}</b></div>
          <div><span>Always-BTC equity</span><b>${money2(benchmark)} · ${signedPct(benchmarkReturn)}</b></div>
          <div><span>V4 edge vs BTC</span><b>${excessDollars>=0?'+':''}${money2(excessDollars)} · ${pctPoints(excessPoints)}</b></div>
          <div><span>Executed sleeve</span><b>${esc(row.executed_label_after||'—')}</b></div>
          <div><span>Model signal</span><b>${esc(row.raw_predicted_label||'—')}</b></div>
          <div><span>Sleeve switch</span><b>${row.sleeve_switch?'YES':'NO'}</b></div>
          <div><span>1h selected net</span><b>${signedPct(row.net_selected_return_1h)}</b></div>
          <div><span>BTC 1h</span><b>${signedPct(row.btc_realized_return_1h)}</b></div>
          <div><span>ALT 1h</span><b>${signedPct(row.alt_realized_return_1h)}</b></div>
          <div><span>Modeled cost</span><b>${signedPct(-Math.abs(Number(row.transaction_cost)||0))} · ${Number.isFinite(+row.cost_bps_assumption)?(+row.cost_bps_assumption).toFixed(0)+' bps':'—'}</b></div>
          <div><span>V4 drawdown</span><b>${signedPct(row.candidate_drawdown)}</b></div>
          <div><span>BTC drawdown</span><b>${signedPct(row.benchmark_drawdown)}</b></div>
          <div><span>Prob BTC / ALT / CASH</span><b>${Number.isFinite(+row.prob_btc)?(+row.prob_btc*100).toFixed(1):'—'}% / ${Number.isFinite(+row.prob_alt)?(+row.prob_alt*100).toFixed(1):'—'}% / ${Number.isFinite(+row.prob_cash)?(+row.prob_cash*100).toFixed(1):'—'}%</b></div>
          <small style="display:block;margin-top:7px;color:#91a6c2">${pinned?'PINNED · click chart again or press Esc to release':'Hover for another hour · click to pin'}</small>`;
      };

      const show=(row,event)=>{
        activeRow=row;
        const xx=x(row._t);
        cross.setAttribute('x1',xx);cross.setAttribute('x2',xx);cross.setAttribute('visibility','visible');
        defs.forEach((def,index)=>{
          const value=+row[def.key],dot=focusDots[index];
          if(Number.isFinite(value)){dot.setAttribute('cx',xx);dot.setAttribute('cy',y(value));dot.setAttribute('visibility','visible')}else dot.setAttribute('visibility','hidden');
        });
        tip.innerHTML=tooltipHtml(row);
        tip.classList.add('visible');
        const rect=svg.getBoundingClientRect();
        const left=Math.max(150,Math.min(rect.width-150,xx/W*rect.width));
        const yValues=defs.map(def=>+row[def.key]).filter(Number.isFinite);
        const yy=yValues.length?Math.min(...yValues.map(y)):pad.t;
        tip.style.left=`${left}px`;
        tip.style.top=`${Math.max(120,Math.min(rect.height-10,yy/H*rect.height))}px`;
      };
      const hide=()=>{cross.setAttribute('visibility','hidden');focusDots.forEach(dot=>dot.setAttribute('visibility','hidden'));tip.classList.remove('visible');activeRow=null};

      svg.addEventListener('pointermove',event=>{
        if(pinned)return;
        const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)/rect.width*W;
        if(px<pad.l||px>W-pad.r){hide();return}
        const target=minT+(px-pad.l)/(W-pad.l-pad.r)*(maxT-minT);
        const row=data.reduce((best,item)=>Math.abs(item._t-target)<Math.abs(best._t-target)?item:best,data[0]);
        show(row,event);
      });
      svg.addEventListener('pointerleave',()=>{if(!pinned)hide()});
      svg.addEventListener('click',event=>{
        if(pinned){pinned=false;if(activeRow)show(activeRow,event);else hide();return}
        const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)/rect.width*W;
        if(px<pad.l||px>W-pad.r)return;
        const target=minT+(px-pad.l)/(W-pad.l-pad.r)*(maxT-minT);
        const row=data.reduce((best,item)=>Math.abs(item._t-target)<Math.abs(best._t-target)?item:best,data[0]);
        pinned=true;show(row,event);
      });
      document.addEventListener('keydown',event=>{if(event.key==='Escape'&&pinned){pinned=false;hide()}});
    }
  }

  function forwardBarChart(id,rows,definitions){
    const svg=document.getElementById(id);if(!svg)return;svg.innerHTML='';const data=(rows||[]).map(row=>({...row,_t:Date.parse(row.timestamp)})).filter(row=>Number.isFinite(row._t));
    if(!data.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">Completed return periods will appear here</text>';return}
    const W=1100,H=260,pad={l:76,r:30,t:36,b:46},values=data.flatMap(row=>definitions.map(def=>+row[def.key])).filter(Number.isFinite),limit=Math.max(.001,...values.map(Math.abs));
    const ns='http://www.w3.org/2000/svg',add=(tag,attrs)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));svg.appendChild(el);return el},y=value=>pad.t+(H-pad.t-pad.b)*(1-(value+limit)/(2*limit)),group=(W-pad.l-pad.r)/data.length,bar=Math.max(2,Math.min(22,group/(definitions.length+1)));
    add('line',{x1:pad.l,x2:W-pad.r,y1:y(0),y2:y(0),stroke:'rgba(242,246,255,.5)','stroke-width':1.5});
    data.forEach((row,i)=>definitions.forEach((def,j)=>{const value=+row[def.key];if(!Number.isFinite(value))return;const x=pad.l+i*group+(group-definitions.length*bar)/2+j*bar;add('rect',{x,y:Math.min(y(value),y(0)),width:Math.max(1,bar-2),height:Math.max(1,Math.abs(y(value)-y(0))),rx:2,fill:def.color,opacity:.9})}));
    definitions.forEach((def,index)=>{const x=pad.l+index*180;add('rect',{x,y:10,width:13,height:13,rx:3,fill:def.color});const label=add('text',{x:x+20,y:21,fill:'#dfeaff','font-size':12,'font-weight':800});label.textContent=def.label});
    const top=add('text',{x:pad.l-8,y:y(limit)+4,fill:'#91a6c2','text-anchor':'end','font-size':11});top.textContent=`+${(limit*100).toFixed(1)}%`;const bottom=add('text',{x:pad.l-8,y:y(-limit)+4,fill:'#91a6c2','text-anchor':'end','font-size':11});bottom.textContent=`-${(limit*100).toFixed(1)}%`;
  }

  function renderForwardCharts(){
    const source=document.getElementById('crypto-forward-chart-data');if(!source)return;let data;try{data=JSON.parse(source.textContent)}catch{return}
    const shared=data.shared_v2||{},v5=data.v5||{};
    forwardLineChart('shared-v2-equity',shared.chart_points,[{key:'candidate',label:'Shared V4',color:'#39e3a1'},{key:'benchmark',label:'Always BTC',color:'#4d8cff'}],{currency:true,interactive:true,hourlySlots:true});
    forwardLineChart('shared-v2-drawdown',shared.chart_points,[{key:'candidate_drawdown',label:'Shared V4',color:'#39e3a1'},{key:'benchmark_drawdown',label:'Always BTC',color:'#4d8cff'}],{percent:true,height:260});
    forwardBarChart('shared-v2-returns',shared.return_points,[{key:'net_return',label:'Selected sleeve',color:'#39e3a1'},{key:'btc_return',label:'BTC',color:'#4d8cff'}]);
    forwardLineChart('shared-v2-probabilities',shared.probability_points,[{key:'btc',label:'BTC probability',color:'#4d8cff'},{key:'alt',label:'ALT probability',color:'#39e3a1'},{key:'cash',label:'CASH probability',color:'#efc56b'}],{percent:true,height:360});
    forwardLineChart('v5-forward-equity',v5.chart_points,[{key:'candidate',label:'Crypto V5',color:'#36d8ff'}],{currency:true});
    forwardLineChart('v5-forward-drawdown',v5.chart_points,[{key:'candidate_drawdown',label:'Crypto V5',color:'#ff6680'}],{percent:true,height:260});
    forwardBarChart('v5-forward-returns',v5.return_points,[{key:'net_return',label:'Net return',color:'#36d8ff'},{key:'gross_return',label:'Gross return',color:'#9b65ff'}]);
  }

  const marketNames={'AAVE-USD':'Aave','ADA-USD':'Cardano','ARB-USD':'Arbitrum','ATOM-USD':'Cosmos','AVAX-USD':'Avalanche','BCH-USD':'Bitcoin Cash','BTC-USD':'Bitcoin','DOGE-USD':'Dogecoin','DOT-USD':'Polkadot','ETC-USD':'Ethereum Classic','ETH-USD':'Ethereum','FIL-USD':'Filecoin','HBAR-USD':'Hedera','ICP-USD':'Internet Computer','INJ-USD':'Injective','LINK-USD':'Chainlink','LTC-USD':'Litecoin','NEAR-USD':'NEAR Protocol','OP-USD':'Optimism','SHIB-USD':'Shiba Inu','SOL-USD':'Solana','SUI-USD':'Sui','UNI-USD':'Uniswap','XLM-USD':'Stellar','XRP-USD':'XRP'};
  const liveMoney=value=>{const n=Number(value);if(!Number.isFinite(n))return'—';const digits=Math.abs(n)>=1000?2:Math.abs(n)>=1?4:8;return'$'+n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:digits})};
  const livePct=value=>{const n=Number(value);if(!Number.isFinite(n))return'—';return`${n>=0?'+':''}${n.toFixed(2)}%`};
  const changeOf=quote=>{const n=Number(quote?.price_percent_chg_24_h);return Number.isFinite(n)?n:null};

  function marketRows(){
    const btcChange=changeOf(marketQuotes['BTC-USD']);
    let rows=Object.entries(marketQuotes).map(([symbol,quote])=>({symbol,quote,price:Number(quote?.price),change:changeOf(quote),relative:Number.isFinite(btcChange)&&Number.isFinite(changeOf(quote))?changeOf(quote)-btcChange:null})).filter(row=>Number.isFinite(row.price)&&Number.isFinite(row.change));
    const query=marketSearch.trim().toLowerCase();
    if(query)rows=rows.filter(row=>row.symbol.toLowerCase().includes(query)||(marketNames[row.symbol]||'').toLowerCase().includes(query));
    if(marketFilter==='gainers')rows=rows.filter(row=>row.change>0);
    if(marketFilter==='losers')rows=rows.filter(row=>row.change<0);
    if(marketFilter==='extreme')rows=rows.filter(row=>Math.abs(row.change)>=5);
    const sorters={symbol:(a,b)=>a.symbol.localeCompare(b.symbol),price:(a,b)=>b.price-a.price,change:(a,b)=>b.change-a.change,relative:(a,b)=>b.relative-a.relative};
    return rows.sort(sorters[marketSort]||sorters.change);
  }

  function renderMarketBoard(updatedAt){
    const all=Object.entries(marketQuotes).map(([symbol,quote])=>({symbol,price:Number(quote?.price),change:changeOf(quote)})).filter(row=>Number.isFinite(row.price)&&Number.isFinite(row.change)).sort((a,b)=>b.change-a.change);
    if(!all.length)return;
    const btc=all.find(row=>row.symbol==='BTC-USD'),up=all.filter(row=>row.change>0).length,down=all.filter(row=>row.change<0).length;
    const ordered=[...all].map(row=>row.change).sort((a,b)=>a-b),mid=Math.floor(ordered.length/2),median=ordered.length%2?ordered[mid]:(ordered[mid-1]+ordered[mid])/2;
    const extreme=all.filter(row=>Math.abs(row.change)>=5).length,leader=all[0],laggard=all[all.length-1],maxAbs=Math.max(0.01,...all.map(row=>Math.abs(row.change)));
    const set=(id,text,cls='')=>{const node=document.getElementById(id);if(node){node.textContent=text;node.className=cls;}};
    set('crypto-market-breadth',`${up} UP · ${down} DOWN`,up>=down?'positive':'negative');
    set('crypto-market-breadth-detail',`${Math.round(up/all.length*100)}% of tracked assets are positive`);
    set('crypto-market-median',livePct(median),median>=0?'positive':'negative');
    set('crypto-market-extremes',`${leader.symbol.replace('-USD','')} / ${laggard.symbol.replace('-USD','')}`);
    set('crypto-market-extremes-detail',`${livePct(leader.change)} · ${livePct(laggard.change)}`);
    set('crypto-market-extreme-count',`${extreme} / ${all.length}`,extreme?'gold':'');
    set('crypto-market-btc-change',btc?livePct(btc.change):'—',btc?.change>=0?'positive':'negative');
    set('crypto-market-btc-price',btc?liveMoney(btc.price):'Price unavailable');
    const stamp=document.getElementById('crypto-live-ticker-stamp');if(stamp){stamp.textContent=`LIVE CACHE · ${updatedAt||'CURRENT'}`;stamp.className='mode';}
    const detail=document.getElementById('crypto-live-ticker-detail');if(detail)detail.textContent=`Auto-refresh · ${new Date().toLocaleTimeString()} · ${all.length} Coinbase USD markets`;
    const rows=marketRows(),root=document.getElementById('crypto-market-board');if(!root)return;
    root.innerHTML=rows.map(row=>`<tr><td><div class="market-asset"><span class="market-coin">${esc(row.symbol.replace('-USD','').slice(0,4))}</span><div><strong>${esc(row.symbol)}</strong><small>${esc(marketNames[row.symbol]||'')}</small></div></div></td><td><strong>${liveMoney(row.price)}</strong></td><td class="market-change-cell ${row.change>=0?'positive':'negative'}"><strong>${livePct(row.change)}</strong><small>${row.change>=0?'GAINING':'DECLINING'}</small></td><td class="${row.relative>=0?'positive':'negative'}">${livePct(row.relative)}</td><td><div class="market-intensity"><span>${Math.abs(row.change).toFixed(1)}%</span><span class="market-intensity-track"><i class="${row.change<0?'down':''}" style="width:${Math.max(2,Math.abs(row.change)/maxAbs*100).toFixed(1)}%"></i></span></div></td></tr>`).join('')||'<tr><td colspan="5">No assets match this search and filter.</td></tr>';
    document.querySelectorAll('[data-market-filter]').forEach(button=>button.classList.toggle('active',button.dataset.marketFilter===marketFilter));
    document.querySelectorAll('[data-market-sort]').forEach(button=>button.classList.toggle('active',button.dataset.marketSort===marketSort));
  }

  function scheduleMarketRefresh(delay=2000){if(marketTimer)window.clearTimeout(marketTimer);marketTimer=window.setTimeout(refreshMarket,delay)}
  async function refreshMarket(){
    if(!document.getElementById('crypto-market-board'))return;
    if(document.hidden){scheduleMarketRefresh();return}
    if(marketInFlight)return;marketInFlight=true;
    try{const response=await fetch('/api/crypto-live',{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();marketQuotes=data.quotes||{};if(!Object.keys(marketQuotes).length)throw new Error(data.error||'No live quotes available');marketLastSuccess=new Date();marketFailures=0;renderMarketBoard(data.updated_at)}catch(error){marketFailures+=1;const stamp=document.getElementById('crypto-live-ticker-stamp');if(stamp){stamp.textContent=marketLastSuccess?'STALE · RETRYING':'UNAVAILABLE · RETRYING';stamp.className='mode negative'}const detail=document.getElementById('crypto-live-ticker-detail');if(detail)detail.textContent=`${error.message} · retry ${marketFailures} · last success ${marketLastSuccess?.toLocaleTimeString()||'none'}`;}finally{marketInFlight=false;scheduleMarketRefresh()}
  }

  function initMarketBoard(){
    if(!document.getElementById('crypto-market-board'))return;
    document.getElementById('crypto-market-search')?.addEventListener('input',event=>{marketSearch=event.target.value;renderMarketBoard()});
    document.querySelectorAll('[data-market-filter]').forEach(button=>button.addEventListener('click',()=>{marketFilter=button.dataset.marketFilter;renderMarketBoard()}));
    document.querySelectorAll('[data-market-sort]').forEach(button=>button.addEventListener('click',()=>{marketSort=button.dataset.marketSort;renderMarketBoard()}));
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshMarket()});
    refreshMarket();
  }
  function initPaperCountdowns(){
    const formatDuration=ms=>{const total=Math.max(0,Math.floor(ms/1000)),hours=Math.floor(total/3600),minutes=Math.floor((total%3600)/60);return hours?hours+'h '+minutes+'m':minutes+'m'};
    const formatPacific=date=>new Intl.DateTimeFormat(undefined,{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(date);
    const update=()=>document.querySelectorAll('[data-paper-countdown]').forEach(node=>{const target=new Date(node.dataset.target),label=node.dataset.label,cadence=node.dataset.cadence,span=node.querySelector('span');if(!span||!Number.isFinite(target.getTime()))return;const now=new Date();if(now<target){span.textContent=label+' begins in '+formatDuration(target-now)+' · '+formatPacific(target);return}if(cadence==='hourly'){const next=new Date(now);next.setUTCMinutes(0,0,0);next.setUTCHours(next.getUTCHours()+1);span.textContent='PAPER TRADING ACTIVE · next hourly boundary '+formatPacific(next)}else{span.textContent='CLEAN WINDOW OPEN · first/next daily decision at 5:00 PM Pacific'}});
    update();window.setInterval(update,30000);
  }

  setupTabs();renderForwardCharts();initMarketBoard();initPaperCountdowns();
})();
