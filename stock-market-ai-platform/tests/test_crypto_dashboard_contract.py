from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_crypto_dashboard_exposes_only_retained_forward_sections():
    template = (ROOT / "webapp/templates/crypto_model_research.html").read_text(encoding="utf-8")
    assert "MODEL COMPARISON" not in template
    assert 'data-crypto-panel="comparison"' not in template
    assert "Historical V5 Reconstruction" not in template
    assert "OVERVIEW" in template
    assert "CRYPTO V5" in template
    assert "SHARED CRYPTO V3" in template


def test_comparison_api_and_browser_request_are_removed():
    app_source = (ROOT / "webapp/app.py").read_text(encoding="utf-8")
    browser_source = (ROOT / "webapp/static/js/crypto_model_research.js").read_text(encoding="utf-8")
    assert "/api/crypto-model-comparison" not in app_source
    assert "get_crypto_model_comparison" not in app_source
    assert "/api/crypto-model-comparison" not in browser_source
    assert "CRYPTO_V5" not in browser_source
