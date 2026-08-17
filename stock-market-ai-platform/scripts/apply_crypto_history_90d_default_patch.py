from pathlib import Path

JS = Path('webapp/static/js/crypto_history_chart.js')
TEMPLATE = Path('webapp/templates/crypto_visual.html')

js = JS.read_text()
tpl = TEMPLATE.read_text()

replacements = [
    ("let range = '1Y';", "let range = '90D';", '[APPLY] 90D default history range'),
    ("fetch('/api/crypto-history?range=1Y'", "fetch('/api/crypto-history?range=90D'", '[APPLY] initial 90D history request'),
    ("fetch('/api/crypto-history'", "fetch('/api/crypto-history?range=90D'", '[APPLY] fallback initial 90D history request'),
]

changed = False
for old, new, message in replacements:
    if old in js:
        js = js.replace(old, new, 1)
        print(message)
        changed = True

old_active = 'data-history-range="1Y">1Y</button><button class="history-btn" type="button" data-history-range="90D">90D</button>'
new_active = 'data-history-range="1Y">1Y</button><button class="history-btn active" type="button" data-history-range="90D">90D</button>'
if old_active in tpl:
    tpl = tpl.replace(old_active, new_active, 1)
    tpl = tpl.replace('class="history-btn active" type="button" data-history-range="1Y"', 'class="history-btn" type="button" data-history-range="1Y"', 1)
    print('[APPLY] 90D active range button')
    changed = True
elif 'data-history-range="90D"' in tpl:
    before = tpl
    tpl = tpl.replace('class="history-btn active" type="button" data-history-range="1Y"', 'class="history-btn" type="button" data-history-range="1Y"', 1)
    tpl = tpl.replace('class="history-btn" type="button" data-history-range="90D"', 'class="history-btn active" type="button" data-history-range="90D"', 1)
    if tpl != before:
        print('[APPLY] 90D active range button')
        changed = True

if not changed:
    raise SystemExit('No 90D default anchors found; inspect current crypto history client before retrying.')

JS.write_text(js)
TEMPLATE.write_text(tpl)

print('Crypto Visual 90D default patch complete.')
print('Initial history view/request defaults to 90D; longer ranges remain available through existing controls.')
print('Presentation/loading only; models, journals, policies, and brokerage settings are unchanged.')
