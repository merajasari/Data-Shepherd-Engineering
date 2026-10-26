"""Prepare small, identity-bound V7 inference inputs without writing evidence.

The first preparation verifies historical files one at a time. Live inference
never loads the historical dataset or refits the frozen daily-context model.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = ROOT / 'data/research/v15/prospective_v7/runtime_inputs'


def _sha(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _read_sealed(path):
    payload = json.loads(Path(path).read_text())
    unsigned = dict(payload)
    digest = unsigned.pop('cache_sha256', None)
    if digest != _sha(unsigned):
        raise ValueError('V15_RUNTIME_CACHE_HASH_MISMATCH')
    return payload


def _write_sealed(path, payload):
    import os
    payload = dict(payload)
    payload['cache_sha256'] = _sha(payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as handle:
        json.dump(payload, handle, sort_keys=True, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    return payload


def _identity(artifact):
    return {key: artifact[key] for key in (
        'prepared_artifact_sha256', 'source_manifest_sha256',
        'contract_sha256', 'slow_context_model_sha256')}


def _manifest(path, artifact):
    manifest = json.loads(Path(path).read_text())
    unsigned = dict(manifest)
    digest = unsigned.pop('manifest_sha256', None)
    if digest != _sha(unsigned) or digest != artifact['source_manifest_sha256']:
        raise ValueError('V15_V7_RUNTIME_HISTORY_MANIFEST_DRIFT')
    symbols = manifest.get('symbols', [])
    if (manifest.get('status') != 'COMPLETE_HISTORICAL_RESEARCH_DATASET'
            or len(symbols) != 101 or len(set(symbols)) != 101 or 'SPY' not in symbols):
        raise ValueError('V15_RUNTIME_SOURCE_INVALID')
    return manifest


def _signatures(manifest, path):
    result = {}
    for symbol in manifest['symbols']:
        source = Path(path).parent / manifest['symbol_metadata'][symbol]['file']
        stat = source.stat()
        result[symbol] = [str(source.resolve()), stat.st_size, stat.st_mtime_ns]
    return result


def prepare_history(artifact, manifest_path, cache_root=CACHE_ROOT):
    from ml.v15.intraday_logistic import _group_sessions
    manifest = _manifest(manifest_path, artifact)
    signatures = _signatures(manifest, manifest_path)
    path = Path(cache_root) / 'historical_closes.json'
    if path.exists():
        saved = _read_sealed(path)
        if saved.get('identity') != _identity(artifact) or saved.get('source_files') != signatures:
            raise ValueError('V15_RUNTIME_HISTORY_CACHE_SOURCE_CHANGED')
        return saved
    closes = {}
    for index, symbol in enumerate(manifest['symbols'], 1):
        item = manifest['symbol_metadata'][symbol]
        source = Path(manifest_path).parent / item['file']
        rows = json.loads(source.read_text())
        if not isinstance(rows, list) or item.get('sha256') != _sha(rows):
            raise ValueError('V15_SOURCE_SYMBOL_SHA_MISMATCH:' + symbol)
        grouped = _group_sessions(rows)
        closes[symbol] = {session: float(bars[-1]['close']) for session, bars in grouped.items()}
        del rows, grouped
        if any(not math.isfinite(value) or value <= 0 for value in closes[symbol].values()):
            raise ValueError('V15_RUNTIME_PREVIOUS_CLOSE_INVALID:' + symbol)
        gc.collect()
        print(f'Historical file verified {index}/101: {symbol}', flush=True)
    if signatures != _signatures(manifest, manifest_path):
        raise ValueError('V15_RUNTIME_SOURCE_CHANGED_DURING_PREPARATION')
    return _write_sealed(path, {'identity': _identity(artifact), 'source_files': signatures, 'closes': closes})


def _prior_session(session, contract):
    day = datetime.fromisoformat(session).date() - timedelta(days=1)
    closures = set(contract['lifecycle']['market_closures'])
    while day.weekday() >= 5 or day.isoformat() in closures:
        day -= timedelta(days=1)
    return day.isoformat()


def load_runtime_inputs(session, artifact, manifest_path, cache_root=CACHE_ROOT):
    from ml.v15.intraday_prospective_v7_contract import load_contract
    manifest = _manifest(manifest_path, artifact)
    history = _read_sealed(Path(cache_root) / 'historical_closes.json')
    cached = _read_sealed(Path(cache_root) / (session + '.json'))
    if history.get('identity') != _identity(artifact) or cached.get('identity') != _identity(artifact):
        raise ValueError('V15_RUNTIME_CACHE_IDENTITY_MISMATCH')
    if history.get('source_files') != _signatures(manifest, manifest_path):
        raise ValueError('V15_RUNTIME_HISTORY_CACHE_SOURCE_CHANGED')
    if cached.get('session') != session or cached.get('daily_session') != _prior_session(session, load_contract()):
        raise ValueError('V15_RUNTIME_DAILY_CONTEXT_STALE')
    if cached.get('history_cache_sha256') != history['cache_sha256']:
        raise ValueError('V15_RUNTIME_HISTORY_CACHE_MISMATCH')
    closes = history['closes']
    candidates = sorted(symbol for symbol in closes if symbol != 'SPY')
    common = sorted(set.intersection(*(set(rows) for rows in closes.values())))
    prior = [value for value in common if value < session]
    if not prior:
        raise ValueError('V15_V7_PREVIOUS_INTRADAY_SESSION_MISSING')
    if sorted(cached['context']) != candidates:
        raise ValueError('V15_RUNTIME_CONTEXT_UNIVERSE_MISMATCH')
    return candidates, {symbol: rows[prior[-1]] for symbol, rows in closes.items()}, cached['context'], cached['daily_session']


def prepare(session=None, cache_root=CACHE_ROOT):
    import numpy as np
    from ml.v15.intraday_logistic import LogisticRegression
    from ml.v15.intraday_hybrid_v2 import (
        DAILY_FEATURE_NAMES, _daily_rows, _pretrain_daily_context,
        _daily_context_for_session, load_contract as load_v2_contract,
    )
    from ml.v15.intraday_prospective_v7_runner import load_prepared_model, MANIFEST_PATH
    from ml.v15.intraday_prospective_v7_contract import load_contract
    artifact = load_prepared_model()
    contract = load_contract()
    session = session or datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    day = datetime.fromisoformat(session).date()
    if day.weekday() >= 5 or session in contract['lifecycle']['market_closures']:
        raise ValueError('V15_RUNTIME_NOT_ELIGIBLE_SESSION')
    history = prepare_history(artifact, MANIFEST_PATH, cache_root)
    candidates = sorted(symbol for symbol in history['closes'] if symbol != 'SPY')
    print('Loading maintained daily features', flush=True)
    # Project only the columns used by the frozen slow model; Spark datasets
    # contain many unrelated features that need not occupy this small VM's RAM.
    import pandas as pd
    import pyarrow.dataset as ds
    from ml.v14.logistic_forward import _universe, _feature_files
    symbols, files = _universe(), _feature_files()
    frames = {}
    for symbol in symbols:
        path = files[symbol]
        names = ds.dataset(path, format="parquet").schema.names
        ts = "timestamp_utc" if "timestamp_utc" in names else "timestamp"
        columns = [ts, *DAILY_FEATURE_NAMES, "target_up_5d"]
        frame = pd.read_parquet(path, columns=columns)
        frame[ts] = pd.to_datetime(frame[ts], utc=True)
        frame = frame.sort_values(ts).drop_duplicates(ts, keep="last")
        for name in (*DAILY_FEATURE_NAMES, "target_up_5d"):
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
        frames[symbol] = frame.rename(columns={ts: "timestamp_utc"}).set_index("timestamp_utc")
    if sorted(symbols) != candidates:
        raise ValueError('V15_V7_RUNTIME_DAILY_UNIVERSE_MISMATCH')
    slow_path = Path(cache_root) / 'frozen_daily_model.json'
    if slow_path.exists():
        sealed = _read_sealed(slow_path)
        if sealed.get('identity') != _identity(artifact):
            raise ValueError('V15_RUNTIME_SLOW_MODEL_IDENTITY_MISMATCH')
        snapshot = sealed['snapshot']
        unsigned = dict(snapshot)
        digest = unsigned.pop('model_sha256', None)
        if digest != _sha(unsigned) or digest != artifact['slow_context_model_sha256']:
            raise ValueError('V15_V7_SLOW_CONTEXT_MODEL_DRIFT')
        if snapshot['feature_names'] != list(DAILY_FEATURE_NAMES):
            raise ValueError('V15_RUNTIME_SLOW_FEATURES_MISMATCH')
        model = LogisticRegression(learning_rate=0.0, epochs=0, l2=0.0)
        model.weights = np.asarray(snapshot['weights'], dtype=float)
        model.bias = float(snapshot['bias'])
        mean = np.asarray(snapshot['feature_mean'], dtype=float)
        std = np.asarray(snapshot['feature_std'], dtype=float)
        mapped = {symbol: _daily_rows(frames[symbol]) for symbol in candidates}
    else:
        print('Reproducing frozen daily-context identity once; no new model selection', flush=True)
        model, mean, std, snapshot, mapped = _pretrain_daily_context(
            frames, candidates, str(artifact['eligible_history_start_session']), load_v2_contract())
        if snapshot['model_sha256'] != artifact['slow_context_model_sha256']:
            raise ValueError('V15_V7_SLOW_CONTEXT_MODEL_DRIFT')
        _write_sealed(slow_path, {'identity': _identity(artifact), 'snapshot': snapshot})
    del frames
    common = sorted(set.intersection(*(set(rows) for rows in mapped.values())))
    prior = [value for value in common if value < session]
    if not prior or prior[-1] != _prior_session(session, contract):
        raise ValueError('V15_RUNTIME_DAILY_CONTEXT_STALE')
    context, _ = _daily_context_for_session(prior[-1], candidates, mapped, model, mean, std)
    payload = _write_sealed(Path(cache_root) / (session + '.json'), {
        'session': session, 'daily_session': prior[-1], 'context': context,
        'identity': _identity(artifact), 'history_cache_sha256': history['cache_sha256'],
        'prepared_at_utc': datetime.now(timezone.utc).isoformat(), 'evidence_written': False,
    })
    load_runtime_inputs(session, artifact, MANIFEST_PATH, cache_root)
    print(f'Prepared {session}; prior daily context {prior[-1]}; {len(context)} stocks; no journal writes', flush=True)
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session')
    parser.add_argument('--verify-snapshot', action='store_true')
    args = parser.parse_args()
    payload = prepare(args.session)
    if args.verify_snapshot:
        from time import monotonic
        from ml.v15.intraday_prospective_v7_runner import (
            SNAPSHOT_PATH, build_decision_payload, load_prepared_model,
        )
        if SNAPSHOT_PATH.exists():
            snapshot = json.loads(SNAPSHOT_PATH.read_text())
            if snapshot.get('session_date') == payload['session']:
                started = monotonic()
                decision = build_decision_payload(snapshot, load_prepared_model())
                print('Read-only decision construction PASS; seconds:', round(monotonic()-started, 2), flush=True)
            else:
                print('Decision benchmark skipped: stored intraday snapshot is from another session', flush=True)
        else:
            print('Decision benchmark skipped: no stored intraday snapshot', flush=True)
