"""Read-only lifecycle projection shared by stock cohort charts."""


def project_cohort_events(events):
    """Expose actual journal events only, with recorded cohort context."""
    allowed = {"DECISION", "ENTRY", "EXIT"}
    rows = [event for event in events if event.get("event_type") in allowed]

    def key(event):
        return (event.get("decision_timestamp_utc") or (str(event.get("event_type")) + ":" + str(event.get(str(event.get("event_type", "")).lower() + "_timestamp_utc")))), event.get("cohort_offset")

    cohorts = {}
    for event in rows:
        cohorts.setdefault(key(event), {})[event["event_type"]] = event
    result = []
    for event in rows:
        kind = event["event_type"]
        timestamp = event.get(kind.lower() + "_timestamp_utc") or event.get("timestamp_utc")
        if not timestamp:
            continue
        cohort = cohorts[key(event)]
        decision = cohort.get("DECISION", {})
        entry = cohort.get("ENTRY", {})
        exit_event = cohort.get("EXIT", {})
        symbols = event.get("symbols") or entry.get("symbols") or decision.get("symbols") or []
        result.append({
            "event_type": kind,
            "timestamp_utc": timestamp,
            "decision_timestamp_utc": event.get("decision_timestamp_utc"),
            "entry_timestamp_utc": entry.get("entry_timestamp_utc"),
            "exit_timestamp_utc": exit_event.get("exit_timestamp_utc"),
            "cohort_offset": event.get("cohort_offset"),
            "symbols": list(symbols),
            "entry_prices": dict(entry.get("entry_prices") or {}),
            "net_portfolio_return": event.get("net_portfolio_return") if kind == "EXIT" else None,
            "spy_return": event.get("spy_return") if kind == "EXIT" else None,
            "net_relative_return": event.get("net_relative_return") if kind == "EXIT" else None,
            "model_sha256": event.get("model_sha256") or decision.get("model_sha256"),
            "frozen_sha256": event.get("frozen_sha256") or decision.get("frozen_sha256"),
        })
    return sorted(result, key=lambda row: str(row["timestamp_utc"]))
