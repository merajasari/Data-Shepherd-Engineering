"""Resumable Coinbase Exchange 15-minute historical candle backfill.

Builds an authoritative REST-candle archive for the 25-product crypto universe.
Historical research data remains separate from forward live WebSocket data.

Key properties:
* Native Coinbase Exchange 15-minute candles (granularity=900).
* Default research request spans 10 years.
* Requests are chunked below Coinbase's 300-candle ceiling.
* Existing rows are merged/deduplicated by (timestamp_utc, product_id).
* Missing intervals are recorded, never synthesized.
* Progress is checkpointed after every successful chunk.
* 429/5xx/network failures use bounded exponential backoff.
* No model fitting, portfolio decisions, or order execution occurs here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Iterable

import pandas as pd
import requests

from ml.crypto_rt import BAR_SECONDS, PRODUCTS

API_ROOT = "https://api.exchange.coinbase.com"
GRANULARITY_SECONDS = BAR_SECONDS
MAX_CANDLES_PER_REQUEST = 300
CHUNK_CANDLES = 288
CHUNK_SECONDS = CHUNK_CANDLES * GRANULARITY_SECONDS
REQUEST_PAUSE_SECONDS = 0.15
MAX_RETRIES = 8
DEFAULT_HISTORY_YEARS = 10

ROOT = Path("data/research/crypto_intraday")
RAW_ROOT = ROOT / "raw_15m"
MANIFEST_ROOT = ROOT / "manifests"
STATUS_PATH = ROOT / "backfill_status.json"
MISSING_PATH = ROOT / "missing_intervals.csv"

COLUMNS = ["timestamp_utc", "product_id", "open", "high", "low", "close", "volume", "bar_seconds", "source"]

@dataclass
class ProductStatus:
    product_id: str
    requested_start_utc: str
    requested_end_utc: str
    cursor_utc: str
    rows_written: int = 0
    requests_completed: int = 0
    missing_bar_count: int = 0
    complete: bool = False
    last_error: str | None = None

def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

def _floor_15m(ts): return _utc(ts).floor("15min")
def _iso(ts): return _utc(ts).isoformat()

def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)

def _normalize_candles(product_id, payload):
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame(columns=COLUMNS)
    rows=[]
    for item in payload:
        if not isinstance(item,(list,tuple)) or len(item)<6: continue
        try:
            epoch,low,high,open_,close,volume=item[:6]
            rows.append({"timestamp_utc":pd.Timestamp(int(epoch),unit="s",tz="UTC"),"product_id":product_id,"open":float(open_),"high":float(high),"low":float(low),"close":float(close),"volume":float(volume),"bar_seconds":GRANULARITY_SECONDS,"source":"coinbase_exchange_rest_candles"})
        except (TypeError,ValueError,OverflowError): pass
    if not rows: return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(rows,columns=COLUMNS).sort_values("timestamp_utc").drop_duplicates(["timestamp_utc","product_id"],keep="last").reset_index(drop=True)

def _request_candles(session, product_id, start, end):
    url=f"{API_ROOT}/products/{product_id}/candles"
    params={"granularity":GRANULARITY_SECONDS,"start":_iso(start),"end":_iso(end)}
    delay=1.0; last_error=None
    for attempt in range(1,MAX_RETRIES+1):
        try:
            r=session.get(url,params=params,timeout=30)
            if r.status_code==200: return r.json()
            if r.status_code in (429,500,502,503,504):
                wait=float(r.headers.get("Retry-After",delay)); last_error=f"HTTP {r.status_code}: {r.text[:300]}"
                time.sleep(min(wait,60)); delay=min(delay*2,60); continue
            raise RuntimeError(f"Coinbase HTTP {r.status_code} for {product_id}: {r.text[:500]}")
        except (requests.RequestException,ValueError) as exc:
            last_error=f"{type(exc).__name__}: {exc}"
            if attempt==MAX_RETRIES: break
            time.sleep(delay); delay=min(delay*2,60)
    raise RuntimeError(last_error or f"Failed Coinbase request for {product_id}")

def _persist(frame):
    if frame.empty: return 0
    frame=frame.copy(); frame["timestamp_utc"]=pd.to_datetime(frame["timestamp_utc"],utc=True)
    for (product_id,month),group in frame.groupby(["product_id",frame["timestamp_utc"].dt.strftime("%Y-%m")],sort=True):
        path=RAW_ROOT/product_id/f"{month}.parquet"; path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            old=pd.read_parquet(path); old["timestamp_utc"]=pd.to_datetime(old["timestamp_utc"],utc=True); combined=pd.concat([old,group[COLUMNS]],ignore_index=True)
        else: combined=group[COLUMNS].copy()
        combined=combined.sort_values("timestamp_utc").drop_duplicates(["timestamp_utc","product_id"],keep="last")
        tmp=path.with_suffix(".parquet.tmp"); combined.to_parquet(tmp,index=False); tmp.replace(path)
    return len(frame)

def _expected_grid(start,end):
    if end<=start: return pd.DatetimeIndex([],tz="UTC")
    return pd.date_range(start=start,end=end-pd.Timedelta(seconds=GRANULARITY_SECONDS),freq="15min",tz="UTC")

def _missing_records(product_id,start,end,frame):
    expected=_expected_grid(start,end)
    actual=pd.DatetimeIndex(pd.to_datetime(frame.get("timestamp_utc",pd.Series(dtype="datetime64[ns]")),utc=True).unique())
    return [{"product_id":product_id,"timestamp_utc":ts.isoformat(),"reason":"coinbase_rest_candle_missing"} for ts in expected.difference(actual)]

def _load_status():
    if not STATUS_PATH.exists(): return {"products":{}}
    try: return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError,OSError): return {"products":{}}

def _save_status(products,start,end):
    _atomic_json(STATUS_PATH,{"generated_at_utc":datetime.now(timezone.utc).isoformat(),"source":"coinbase_exchange_rest_candles","bar_seconds":GRANULARITY_SECONDS,"requested_start_utc":_iso(start),"requested_end_utc":_iso(end),"product_count":len(products),"completed_product_count":sum(1 for p in products.values() if p.complete),"products":{k:asdict(v) for k,v in sorted(products.items())}})

def _initial_product_status(product_id,start,end,previous):
    prev=previous.get("products",{}).get(product_id,{})
    same=prev.get("requested_start_utc")==_iso(start) and prev.get("requested_end_utc")==_iso(end)
    cursor=_utc(prev.get("cursor_utc")) if same and prev.get("cursor_utc") else start
    return ProductStatus(product_id,_iso(start),_iso(end),_iso(max(start,cursor)),int(prev.get("rows_written",0)) if same else 0,int(prev.get("requests_completed",0)) if same else 0,int(prev.get("missing_bar_count",0)) if same else 0,bool(prev.get("complete",False)) if same else False,None)

def _append_missing(records):
    if not records: return
    ROOT.mkdir(parents=True,exist_ok=True); new=pd.DataFrame(records)
    old=pd.read_csv(MISSING_PATH) if MISSING_PATH.exists() else pd.DataFrame(columns=new.columns)
    out=pd.concat([old,new],ignore_index=True).drop_duplicates(["product_id","timestamp_utc","reason"]).sort_values(["product_id","timestamp_utc"])
    tmp=MISSING_PATH.with_suffix(".csv.tmp"); out.to_csv(tmp,index=False); tmp.replace(MISSING_PATH)

def run_backfill(start,end,products):
    start=_floor_15m(start); end=_floor_15m(end)
    if end<=start: raise ValueError("end must be after start")
    selected=tuple(dict.fromkeys(products)); unknown=sorted(set(selected)-set(PRODUCTS))
    if unknown: raise ValueError("Unknown products: "+", ".join(unknown))
    ROOT.mkdir(parents=True,exist_ok=True); RAW_ROOT.mkdir(parents=True,exist_ok=True); MANIFEST_ROOT.mkdir(parents=True,exist_ok=True)
    previous=_load_status(); statuses={p:_initial_product_status(p,start,end,previous) for p in selected}; _save_status(statuses,start,end)
    session=requests.Session(); session.headers.update({"User-Agent":"DataShepherdEngineering-CryptoResearch/1.0"})
    for product_id in selected:
        status=statuses[product_id]
        if status.complete: print(f"[SKIP] {product_id} already complete"); continue
        cursor=_utc(status.cursor_utc); print(f"[START] {product_id} from {cursor} to {end}")
        while cursor<end:
            chunk_end=min(cursor+pd.Timedelta(seconds=CHUNK_SECONDS),end)
            try:
                frame=_normalize_candles(product_id,_request_candles(session,product_id,cursor,chunk_end))
                if not frame.empty: frame=frame[(frame.timestamp_utc>=cursor)&(frame.timestamp_utc<chunk_end)].copy()
                missing=_missing_records(product_id,cursor,chunk_end,frame); _persist(frame); _append_missing(missing)
                status.rows_written+=len(frame); status.requests_completed+=1; status.missing_bar_count+=len(missing); status.cursor_utc=_iso(chunk_end); status.last_error=None; cursor=chunk_end; _save_status(statuses,start,end)
                if status.requests_completed%100==0 or cursor>=end: print(f"  {product_id}: requests={status.requests_completed} rows={status.rows_written} missing={status.missing_bar_count} cursor={cursor}")
                time.sleep(REQUEST_PAUSE_SECONDS)
            except Exception as exc:
                status.last_error=f"{type(exc).__name__}: {exc}"; _save_status(statuses,start,end); raise
        status.complete=True; status.cursor_utc=_iso(end); _save_status(statuses,start,end); print(f"[SUCCESS] {product_id}")
    manifest={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"source":"coinbase_exchange_rest_candles","api_root":API_ROOT,"granularity_seconds":GRANULARITY_SECONDS,"request_chunk_candles":CHUNK_CANDLES,"requested_start_utc":_iso(start),"requested_end_utc":_iso(end),"products":list(selected),"storage_root":str(RAW_ROOT),"missing_intervals":str(MISSING_PATH),"status":str(STATUS_PATH),"policy":"Missing candles are recorded and never synthesized. Pre-listing periods therefore remain missing; historical REST candles remain separate from live WebSocket approximations."}
    path=MANIFEST_ROOT/f"backfill_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.json"; _atomic_json(path,manifest); return manifest

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    default_start=(pd.Timestamp.now(tz="UTC")-pd.DateOffset(years=DEFAULT_HISTORY_YEARS)).floor("D").isoformat()
    ap.add_argument("--start",default=default_start,help=f"UTC start timestamp; default is {DEFAULT_HISTORY_YEARS} years ago.")
    ap.add_argument("--end",default=pd.Timestamp.now(tz="UTC").floor("15min").isoformat(),help="UTC exclusive end timestamp; default current completed 15-minute boundary.")
    ap.add_argument("--products",nargs="*",default=list(PRODUCTS),help="Optional subset of configured product IDs.")
    args=ap.parse_args(argv); manifest=run_backfill(_utc(args.start),_utc(args.end),args.products)
    print("CRYPTO INTRADAY 15-MINUTE BACKFILL COMPLETE"); print("="*72); print(f"Start: {manifest['requested_start_utc']}"); print(f"End:   {manifest['requested_end_utc']}"); print(f"Products: {len(manifest['products'])}"); print(f"Bars: {manifest['storage_root']}"); print(f"Status: {manifest['status']}"); print(f"Missing intervals: {manifest['missing_intervals']}")

if __name__=="__main__": main()
