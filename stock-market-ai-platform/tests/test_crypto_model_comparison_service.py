import json

from webapp.services.crypto_model_comparison_service import get_crypto_model_comparison


def test_missing_artifact_is_actionable(tmp_path):
    payload = get_crypto_model_comparison(tmp_path / "missing.json")
    assert payload["available"] is False
    assert payload["build_command"] == "python -m ml.build_crypto_model_comparison"


def test_valid_artifact_is_returned(tmp_path):
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps({"schema_version": 1, "starting_capital": 100000, "series": [], "research_safety": {"brokerage_orders": False}}))
    payload = get_crypto_model_comparison(path)
    assert payload["available"] is True
    assert payload["research_safety"]["brokerage_orders"] is False
