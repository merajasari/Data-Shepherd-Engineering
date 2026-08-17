from pathlib import Path

TEMPLATE = Path('webapp/templates/crypto_visual.html')
text = TEMPLATE.read_text()

CSS = r'''
/* CRYPTO RELATIONSHIP EXPLORER */
.relationship-card{margin-top:20px;border-color:rgba(77,140,255,.42)}
.relationship-metrics{grid-template-columns:repeat(4,1fr);margin:16px 0}
.relationship-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}
.relationship-search{min-width:260px;flex:1;padding:10px 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-weight:800}
.relationship-btn{padding:9px 13px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}
.relationship-btn:hover,.relationship-btn.active{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}
.relationship-chips{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 18px}
.relationship-chip{display:flex;gap:7px;align-items:center;padding:8px 10px;border:1px solid var(--border);border-radius:999px;background:rgba(8,20,36,.45);color:var(--muted);cursor:pointer;opacity:.55}
.relationship-chip span{font-size:.74rem}.relationship-chip.active{opacity:1;color:var(--text);border-color:rgba(54,216,255,.7);background:rgba(54,216,255,.08)}
.relationship-layout{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:18px;margin-top:16px}
.relationship-panel{background:rgba(8,20,36,.55);border:1px solid var(--border);border-radius:18px;padding:16px;min-width:0}
.relationship-scroll{overflow:auto;max-width:100%}
.relationship-scroll table{border-collapse:separate;border-spacing:4px;min-width:max-content}
.relationship-scroll th{position:sticky;background:#0c1a2d;color:var(--muted);font-size:.72rem;padding:7px;z-index:1}
.relationship-scroll thead th{top:0}.relationship-scroll tbody th{left:0}
.relationship-scroll td{width:50px;height:42px;text-align:center;border-radius:8px;font-size:.74rem;cursor:help;transition:transform .12s ease}
.relationship-scroll td:hover{transform:scale(1.08);outline:2px solid rgba(54,216,255,.7)}
.relationship-bar-row{display:grid;grid-template-columns:28px 105px 1fr 95px;gap:9px;align-items:center;padding:8px 0;border-bottom:1px solid rgba(120,155,205,.10)}
.relationship-bar-row:last-child{border-bottom:0}.relationship-rank{color:var(--muted);font-size:.78rem}.relationship-symbol{display:flex;flex-direction:column}.relationship-symbol span{color:var(--muted);font-size:.7rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.relationship-bar-track{height:10px;background:#07101f;border-radius:99px;position:relative;overflow:hidden}.relationship-bar-track b{position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(242,246,255,.25)}.relationship-bar-track i{position:absolute;top:0;bottom:0;border-radius:99px}.relationship-bar-track i.up{background:var(--green)}.relationship-bar-track i.down{background:var(--red)}.relationship-values{text-align:right;display:flex;flex-direction:column}.relationship-values small{color:var(--muted);font-size:.68rem}.relationship-empty{color:var(--muted);padding:24px;text-align:center}
@media(max-width:1050px){.relationship-layout{grid-template-columns:1fr}.relationship-metrics{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){.relationship-metrics{grid-template-columns:1fr}.relationship-bar-row{grid-template-columns:24px 85px 1fr 80px}}
'''

SECTION = r'''
<section id="crypto-relationship-explorer" class="card relationship-card"><div class="label">CRYPTO MARKET RELATIONSHIPS</div><h2>What is moving together — and what is breaking away?</h2><p class="muted">Daily-return correlation from the same historical archive used above. Correlation measures how similarly two assets moved over the selected window; BTC-relative performance shows which selected assets gained or lost ground versus Bitcoin.</p><div class="grid relationship-metrics"><div class="metric"><span>SELECTED ASSETS</span><strong id="relationship-selected-count">—</strong></div><div class="metric"><span>LOOKBACK</span><strong id="relationship-window">90 DAYS</strong></div><div class="metric"><span>PAIR COMPARISONS</span><strong id="relationship-pair-count">—</strong></div><div class="metric"><span>BTC PERIOD RETURN</span><strong id="relationship-btc-return">—</strong></div></div><div class="relationship-toolbar"><strong class="muted">WINDOW</strong><button class="relationship-btn" type="button" data-relationship-window="30">30D</button><button class="relationship-btn active" type="button" data-relationship-window="90">90D</button><button class="relationship-btn" type="button" data-relationship-window="365">1Y</button><input id="relationship-search" class="relationship-search" type="search" placeholder="Filter BTC, Ethereum, Solana…" aria-label="Filter relationship assets"><button id="relationship-select-default" class="relationship-btn" type="button">MAJORS</button><button id="relationship-select-all" class="relationship-btn" type="button">ALL 25</button><button id="relationship-clear" class="relationship-btn" type="button">CLEAR</button><span id="relationship-load-status" class="mode">LOADING RELATIONSHIPS</span></div><div id="relationship-chips" class="relationship-chips"></div><div class="relationship-layout"><div class="relationship-panel"><div class="chart-title">Correlation heatmap</div><div class="chart-subtitle">+1 means two cryptos moved very similarly; 0 means little linear relationship; negative values mean they tended to move in opposite directions. Hover any cell for overlap details.</div><div id="relationship-heatmap" class="relationship-scroll" style="margin-top:14px"></div></div><div class="relationship-panel"><div class="chart-title">Performance vs Bitcoin</div><div class="chart-subtitle">Period return minus BTC's return for the same lookback. Positive means the asset outperformed BTC.</div><div id="relationship-relative" style="margin-top:12px"></div></div></div><div class="warning" style="margin-top:14px">Descriptive visualization only. It reuses archived daily closes derived from the reconciled 15-minute history and does not alter research features, models, frozen policies, journals, or brokerage settings.</div></section>
'''

if '/* CRYPTO RELATIONSHIP EXPLORER */' not in text:
    if '</style>' not in text:
        raise SystemExit('Cannot apply relationship styles: </style> not found')
    text = text.replace('</style>', CSS + '\n</style>', 1)
    print('[APPLY] relationship explorer styles')
else:
    print('[SKIP] relationship explorer styles')

if 'id="crypto-relationship-explorer"' not in text:
    anchor = '<section class="card hero-card"><div class="label">LIVE MARKET PULSE</div>'
    if anchor not in text:
        raise SystemExit('Cannot insert relationship explorer: Live Market Pulse anchor not found')
    text = text.replace(anchor, SECTION + '\n' + anchor, 1)
    print('[APPLY] relationship explorer section')
else:
    print('[SKIP] relationship explorer section')

script_tag = '<script src="/static/js/crypto_relationship_explorer.js"></script>'
if script_tag not in text:
    anchor = '<script src="/static/js/crypto_history_chart.js"></script>'
    if anchor not in text:
        raise SystemExit('Cannot add relationship script: history script anchor not found')
    text = text.replace(anchor, anchor + script_tag, 1)
    print('[APPLY] relationship explorer script')
else:
    print('[SKIP] relationship explorer script')

TEMPLATE.write_text(text)
print('Crypto Visual relationship explorer patch complete.')
print('Read-only analytics: existing history data is reused; models, journals, and brokerage settings are unchanged.')
