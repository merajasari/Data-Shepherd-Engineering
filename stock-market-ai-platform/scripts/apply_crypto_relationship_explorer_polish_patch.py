from pathlib import Path

TEMPLATE = Path('webapp/templates/crypto_visual.html')
SCRIPT = Path('webapp/static/js/crypto_relationship_explorer.js')

html = TEMPLATE.read_text()
js = SCRIPT.read_text()

CSS = r'''
/* CRYPTO RELATIONSHIP EXPLORER POLISH */
.relationship-insights{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0 16px}
.relationship-insight{border:1px solid rgba(120,155,205,.16);border-radius:14px;background:rgba(8,20,36,.42);padding:14px}
.relationship-insight span{display:block;color:var(--muted);font-size:.68rem;font-weight:900;letter-spacing:.08em}
.relationship-insight strong{display:block;margin-top:6px;font-size:1.05rem}
.relationship-insight small{display:block;margin-top:4px;color:var(--muted)}
.relationship-corr-legend{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:12px;color:var(--muted);font-size:.76rem}
.relationship-corr-gradient{height:10px;min-width:190px;flex:1;max-width:310px;border-radius:99px;border:1px solid rgba(120,155,205,.2);background:linear-gradient(90deg,rgba(255,102,128,.9),rgba(145,166,194,.18) 50%,rgba(57,227,161,.9))}
.relationship-corr-legend b{color:var(--text);font-size:.72rem}
@media(max-width:650px){.relationship-insights{grid-template-columns:1fr}}
'''

INSIGHTS = r'''<div class="relationship-insights"><div class="relationship-insight"><span>MOST CORRELATED PAIR</span><strong id="relationship-most-pair">—</strong><small id="relationship-most-value">Select at least two assets</small></div><div class="relationship-insight"><span>LEAST CORRELATED PAIR</span><strong id="relationship-least-pair">—</strong><small id="relationship-least-value">Select at least two assets</small></div></div>'''

LEGEND = r'''<div class="relationship-corr-legend"><b>-1 opposite</b><div class="relationship-corr-gradient" aria-label="Correlation color scale from negative one through zero to positive one"></div><b>0 unrelated</b><b>+1 together</b></div>'''

if '/* CRYPTO RELATIONSHIP EXPLORER POLISH */' not in html:
    if '</style>' not in html:
        raise SystemExit('Cannot apply relationship polish styles: </style> not found')
    html = html.replace('</style>', CSS + '\n</style>', 1)
    print('[APPLY] relationship polish styles')
else:
    print('[SKIP] relationship polish styles')

if 'id="relationship-most-pair"' not in html:
    anchor = '<div id="relationship-chips" class="relationship-chips"></div>'
    if anchor not in html:
        raise SystemExit('Cannot add relationship pair summaries: chip anchor not found')
    html = html.replace(anchor, anchor + INSIGHTS, 1)
    print('[APPLY] strongest and weakest relationship summaries')
else:
    print('[SKIP] strongest and weakest relationship summaries')

if 'relationship-corr-gradient' not in html:
    anchor = 'Hover any cell for overlap details.</div><div id="relationship-heatmap"'
    if anchor not in html:
        raise SystemExit('Cannot add correlation legend: heatmap subtitle anchor not found')
    html = html.replace(anchor, 'Hover any cell for overlap details.</div>' + LEGEND + '<div id="relationship-heatmap"', 1)
    print('[APPLY] correlation color legend')
else:
    print('[SKIP] correlation color legend')

HELPER = r'''
  function renderPairHighlights() {
    const syms=activeSymbols();
    const mostPair=document.getElementById('relationship-most-pair');
    const mostValue=document.getElementById('relationship-most-value');
    const leastPair=document.getElementById('relationship-least-pair');
    const leastValue=document.getElementById('relationship-least-value');
    if(!mostPair||!mostValue||!leastPair||!leastValue) return;
    if(syms.length<2){
      mostPair.textContent='—'; mostValue.textContent='Select at least two assets';
      leastPair.textContent='—'; leastValue.textContent='Select at least two assets';
      return;
    }
    const maps=Object.fromEntries(syms.map(s=>[s,returnsMap(s)]));
    const pairs=[];
    for(let i=0;i<syms.length;i++) for(let j=i+1;j<syms.length;j++) {
      const result=pearson(maps[syms[i]],maps[syms[j]]);
      if(Number.isFinite(result.r)) pairs.push({a:syms[i],b:syms[j],r:result.r,n:result.n});
    }
    if(!pairs.length){
      mostPair.textContent='—'; mostValue.textContent='Not enough overlapping observations';
      leastPair.textContent='—'; leastValue.textContent='Not enough overlapping observations';
      return;
    }
    pairs.sort((a,b)=>b.r-a.r);
    const most=pairs[0], least=pairs[pairs.length-1];
    mostPair.textContent=`${short(most.a)} + ${short(most.b)}`;
    mostValue.textContent=`${most.r.toFixed(2)} correlation · ${most.n} overlapping daily returns`;
    leastPair.textContent=`${short(least.a)} + ${short(least.b)}`;
    leastValue.textContent=`${least.r.toFixed(2)} correlation · ${least.n} overlapping daily returns`;
  }
'''

if 'function renderPairHighlights()' not in js:
    anchor = '  function renderHeatmap() {'
    if anchor not in js:
        raise SystemExit('Cannot add pair highlight logic: renderHeatmap anchor not found')
    js = js.replace(anchor, HELPER + '\n' + anchor, 1)
    print('[APPLY] pair highlight calculations')
else:
    print('[SKIP] pair highlight calculations')

old = '  function renderAll(){renderSummary();renderChips();renderHeatmap();renderRelative();}'
new = '  function renderAll(){renderSummary();renderChips();renderPairHighlights();renderHeatmap();renderRelative();}'
if new not in js:
    if old not in js:
        raise SystemExit('Cannot wire pair highlights into render cycle: renderAll anchor not found')
    js = js.replace(old, new, 1)
    print('[APPLY] pair highlights render cycle')
else:
    print('[SKIP] pair highlights render cycle')

# Slightly strengthen heatmap contrast while preserving the same semantic colors.
old_pos = "if(r>=0) return `background:rgba(57,227,161,${0.08+mag*0.58});color:${mag>.55?'#04150f':'#dffcf1'}`;"
new_pos = "if(r>=0) return `background:rgba(57,227,161,${0.12+mag*0.70});color:${mag>.48?'#04150f':'#dffcf1'};box-shadow:inset 0 0 0 1px rgba(57,227,161,${0.10+mag*0.24})`;"
old_neg = "return `background:rgba(255,102,128,${0.08+mag*0.58});color:${mag>.55?'#1b0509':'#ffe9ed'}`;"
new_neg = "return `background:rgba(255,102,128,${0.12+mag*0.70});color:${mag>.48?'#1b0509':'#ffe9ed'};box-shadow:inset 0 0 0 1px rgba(255,102,128,${0.10+mag*0.24})`;"
if old_pos in js:
    js = js.replace(old_pos, new_pos, 1)
    print('[APPLY] stronger positive heatmap contrast')
elif new_pos in js:
    print('[SKIP] stronger positive heatmap contrast')
else:
    raise SystemExit('Cannot strengthen positive heatmap contrast: expected cell style not found')

if old_neg in js:
    js = js.replace(old_neg, new_neg, 1)
    print('[APPLY] stronger negative heatmap contrast')
elif new_neg in js:
    print('[SKIP] stronger negative heatmap contrast')
else:
    raise SystemExit('Cannot strengthen negative heatmap contrast: expected cell style not found')

TEMPLATE.write_text(html)
SCRIPT.write_text(js)
print('Crypto Visual relationship explorer polish patch complete.')
print('Presentation only; historical data, models, journals, policies, and brokerage settings are unchanged.')
