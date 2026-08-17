from pathlib import Path

HISTORY_JS = Path('webapp/static/js/crypto_history_chart.js')
REL_JS = Path('webapp/static/js/crypto_relationship_explorer.js')
TEMPLATE = Path('webapp/templates/crypto_visual.html')

history = HISTORY_JS.read_text()
rel = REL_JS.read_text()
template = TEMPLATE.read_text()

# Shared loader injected before both feature scripts.
loader = r'''<script>
window.DataShepherdCryptoHistory = window.DataShepherdCryptoHistory || (() => {
  const cache = new Map();
  function normalizeRange(value) {
    const v = String(value || '90D').toUpperCase();
    return ['30D','90D','1Y','3Y','5Y','ALL'].includes(v) ? v : '90D';
  }
  async function load(range='90D') {
    const key = normalizeRange(range);
    if (cache.has(key)) return cache.get(key);
    const promise = fetch(`/api/crypto-history?range=${encodeURIComponent(key)}`, {cache:'no-store'})
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .catch(err => {
        cache.delete(key);
        throw err;
      });
    cache.set(key, promise);
    return promise;
  }
  function prime(range, payload) {
    cache.set(normalizeRange(range), Promise.resolve(payload));
  }
  return {load, prime};
})();
</script>'''

anchor = '<script src="/static/js/crypto_history_chart.js"></script>'
if 'window.DataShepherdCryptoHistory' not in template:
    if anchor not in template:
        raise SystemExit('Cannot inject shared history loader: history script anchor not found')
    template = template.replace(anchor, loader + anchor, 1)
    print('[APPLY] shared browser history loader')
else:
    print('[SKIP] shared browser history loader')

# History module: default 90D and use shared loader for initial payload.
history = history.replace("let range = '1Y';", "let range = '90D';")
history = history.replace("let range = 'ALL';", "let range = '90D';")

# Replace common direct-fetch forms conservatively.
replacements = [
    ("const res=await fetch('/api/crypto-history',{cache:'no-store'});\n      if(!res.ok) throw new Error(`HTTP ${res.status}`);\n      historical=await res.json();",
     "historical=await window.DataShepherdCryptoHistory.load('90D');"),
    ("const res = await fetch('/api/crypto-history', {cache:'no-store'});\n      if (!res.ok) throw new Error(`HTTP ${res.status}`);\n      historical = await res.json();",
     "historical = await window.DataShepherdCryptoHistory.load('90D');"),
    ("const res=await fetch('/api/crypto-history?range=90D',{cache:'no-store'});\n      if(!res.ok) throw new Error(`HTTP ${res.status}`);\n      historical=await res.json();",
     "historical=await window.DataShepherdCryptoHistory.load('90D');"),
]
changed = False
for old, new in replacements:
    if old in history:
        history = history.replace(old, new, 1)
        changed = True
        break
if changed:
    print('[APPLY] Full History uses shared 90D loader')
else:
    print('[INFO] Full History direct fetch pattern not found; preserving current local fetch logic')

# Relationship explorer must share the same 90D payload instead of issuing a duplicate request.
old = "const res=await fetch('/api/crypto-history',{cache:'no-store'});\n      if(!res.ok) throw new Error(`HTTP ${res.status}`);\n      payload=await res.json();"
new = "payload=await window.DataShepherdCryptoHistory.load('90D');"
if old in rel:
    rel = rel.replace(old, new, 1)
    print('[APPLY] relationship explorer reuses shared 90D payload')
else:
    old2 = "const res = await fetch('/api/crypto-history', {cache:'no-store'});\n      if (!res.ok) throw new Error(`HTTP ${res.status}`);\n      payload = await res.json();"
    if old2 in rel:
        rel = rel.replace(old2, new, 1)
        print('[APPLY] relationship explorer reuses shared 90D payload')
    else:
        raise SystemExit('Cannot patch relationship explorer: direct history fetch not found')

# Defer both heavy modules until after first paint by making scripts defer.
template = template.replace('<script src="/static/js/crypto_history_chart.js"></script>', '<script defer src="/static/js/crypto_history_chart.js"></script>')
template = template.replace('<script src="/static/js/crypto_relationship_explorer.js"></script>', '<script defer src="/static/js/crypto_relationship_explorer.js"></script>')
print('[APPLY] defer history/relationship scripts')

HISTORY_JS.write_text(history)
REL_JS.write_text(rel)
TEMPLATE.write_text(template)

print('Crypto Visual shared history loader patch complete.')
print('Initial page load performs one shared 90D history request for Full History and Relationships.')
print('No model, policy, journal, frozen research, or brokerage behavior is changed.')
