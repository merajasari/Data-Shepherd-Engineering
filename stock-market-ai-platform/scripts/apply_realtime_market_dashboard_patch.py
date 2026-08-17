"""Patch Flask + templates for read-only real-time stock/crypto display."""
from pathlib import Path

APP = Path('webapp/app.py')
INDEX = Path('webapp/templates/index.html')
CRYPTO = Path('webapp/templates/crypto.html')


def replace_once(path, old, new, label):
    text = path.read_text(encoding='utf-8')
    if new in text:
        print(f'[SKIP] {label}')
        return
    if old not in text:
        raise SystemExit(f'Patch anchor missing for {label}: {path}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')
    print(f'[APPLY] {label}')


replace_once(
    APP,
    'from webapp.services.live_market_service import get_all_live_quotes, get_live_quote  # noqa: E402\n',
    'from webapp.services.live_market_service import get_all_live_quotes, get_live_quote  # noqa: E402\nfrom webapp.services.crypto_live_market_service import get_all_crypto_live_tickers  # noqa: E402\n',
    'crypto live ticker service import',
)
replace_once(
    APP,
    "        if request.path in {\"/\", \"/dashboard\", \"/crypto\"}:\n            scripts.append('<script src=\"/static/js/signup_button.js\"></script>')\n",
    "        if request.path in {\"/\", \"/dashboard\", \"/crypto\"}:\n            scripts.append('<script src=\"/static/js/signup_button.js\"></script>')\n        if request.path in {\"/dashboard\", \"/crypto\"}:\n            scripts.append('<script src=\"/static/js/realtime_market_refresh.js\"></script>')\n",
    'real-time refresh script injection',
)
replace_once(
    APP,
    '@app.route("/api/live")\n@login_required\ndef api_live_quotes():\n    return jsonify(get_all_live_quotes())\n',
    '@app.route("/api/live")\n@login_required\ndef api_live_quotes():\n    return jsonify(get_all_live_quotes())\n\n\n@app.route("/api/crypto-live")\n@login_required\ndef api_crypto_live_quotes():\n    return jsonify(get_all_crypto_live_tickers())\n',
    'crypto live API route',
)
replace_once(
    INDEX,
    '<td>${{ "%.2f"|format(row.display_price) }}</td><td class="{% if row.eod_change_pct < 0 %}negative{% else %}positive{% endif %}">',
    '<td data-live-price-symbol="{{ row.symbol }}">${{ "%.2f"|format(row.display_price) }}</td><td class="{% if row.eod_change_pct < 0 %}negative{% else %}positive{% endif %}">',
    'stock top-10 live price hooks',
)
replace_once(
    CRYPTO,
    '<nav class="tabs"><a class="tab" href="{{ url_for(\'dashboard\') }}">STOCKS</a><a class="tab active" href="{{ url_for(\'crypto_dashboard\') }}">CRYPTO</a></nav>\n',
    '<nav class="tabs"><a class="tab" href="{{ url_for(\'dashboard\') }}">STOCKS</a><a class="tab active" href="{{ url_for(\'crypto_dashboard\') }}">CRYPTO</a></nav>\n<section class="card live" style="margin-bottom:22px"><div class="label">COINBASE REAL-TIME MARKET</div><h2>Live Crypto Price Movement</h2><p class="muted">Public Coinbase ticker stream for immediate price visibility. Display-only: frozen 15-minute research candles and model decisions remain unchanged.</p><div id="crypto-live-ticker-stamp" class="mode">WAITING FOR LIVE TICKS</div><div id="crypto-live-ticker-grid" class="grid metrics" style="margin-top:18px"><div class="warning">Waiting for Coinbase real-time ticker data…</div></div></section>\n',
    'crypto real-time ticker board',
)
print('Real-time market dashboard patch complete.')
