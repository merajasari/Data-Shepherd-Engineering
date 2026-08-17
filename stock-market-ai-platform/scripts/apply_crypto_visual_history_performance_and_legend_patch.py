from pathlib import Path

SERVICE = Path('webapp/services/crypto_history_service.py')
HISTORY_JS = Path('webapp/static/js/crypto_history_chart.js')
TEMPLATE = Path('webapp/templates/crypto_visual.html')

SERVICE_SOURCE = r'''"""Read-only historical crypto chart data from the authoritative 15-minute archive.

The archive remains the source of truth. For browser-scale charts we reduce each
product to its last observed close per UTC day. An archive-signature cache avoids
re-reading unchanged Parquet history on every dashboard refresh while invalidating
automatically whenever the product archive changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from ml.crypto_rt import PRODUCTS

RAW_ROOT = Path("data/research/crypto_intraday/raw_15m")
_DAILY_CACHE: dict[str, tuple[tuple, pd.DataFrame]] = {}


def _product_paths(product_id: str) -> list[Path]:
    return sorted((RAW_ROOT / product_id).glob("*.parquet"))


def _archive_signature(paths: list[Path]) -> tuple:
    """Cheap invalidation signature for a product's historical archive."""
    signature = []
    for path in paths:
        try:
            stat = path.stat()
            signature.append((path.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            signature.append((path.name, None, None))
    return tuple(signature)


def _read_product_paths(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        try:
            frame = pd.read_parquet(path, columns=["timestamp_utc", "close"])
        except Exception:
            continue
        if len(frame):
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["timestamp_utc", "close"])

    out = pd.concat(frames, ignore_index=True)
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["timestamp_utc", "close"])
    out = out[out["close"] > 0]
    out = out.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    return out


def _daily_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["date"] = out["timestamp_utc"].dt.floor("D")
    daily = out.groupby("date", as_index=False).tail(1).copy()
    daily = daily[["date", "timestamp_utc", "close"]].sort_values("date")
    first = float(daily.iloc[0]["close"])
    daily["index_100"] = daily["close"] / first * 100.0
    return daily


def _daily_product(product_id: str) -> pd.DataFrame:
    paths = _product_paths(product_id)
    signature = _archive_signature(paths)
    cached = _DAILY_CACHE.get(product_id)
    if cached is not None and cached[0] == signature:
        return cached[1]

    daily = _daily_history(_read_product_paths(paths))
    _DAILY_CACHE[product_id] = (signature, daily)
    return daily


def get_crypto_history_payload(products: Iterable[str] | None = None) -> dict:
    requested = list(products or PRODUCTS)
    requested = [p for p in requested if p in PRODUCTS]
    if not requested:
        requested = list(PRODUCTS)

    series = {}
    global_start = None
    global_end = None
    total_points = 0

    for product_id in requested:
        daily = _daily_product(product_id)
        if daily.empty:
            series[product_id] = {
                "available": False,
                "start_utc": None,
                "end_utc": None,
                "point_count": 0,
                "points": [],
            }
            continue

        start = daily.iloc[0]["timestamp_utc"]
        end = daily.iloc[-1]["timestamp_utc"]
        global_start = start if global_start is None else min(global_start, start)
        global_end = end if global_end is None else max(global_end, end)
        points = [
            {
                "t": row.timestamp_utc.isoformat(),
                "close": float(row.close),
                "index_100": float(row.index_100),
            }
            for row in daily.itertuples(index=False)
        ]
        total_points += len(points)
        series[product_id] = {
            "available": True,
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "point_count": len(points),
            "first_close": float(daily.iloc[0]["close"]),
            "last_historical_close": float(daily.iloc[-1]["close"]),
            "points": points,
        }

    return {
        "status": "ok",
        "source": str(RAW_ROOT),
        "resolution": "daily_last_authoritative_15m_close",
        "underlying_archive_resolution": "15m",
        "normalization": "Each product begins at index 100 on its own first available observation.",
        "product_count": len(requested),
        "total_chart_points": total_points,
        "global_start_utc": global_start.isoformat() if global_start is not None else None,
        "global_end_utc": global_end.isoformat() if global_end is not None else None,
        "series": series,
        "cache": {
            "strategy": "archive_signature_per_product",
            "cached_products": len(_DAILY_CACHE),
        },
        "brokerage_orders": False,
    }
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f'[SKIP] {label}')
        return text
    if old not in text:
        raise SystemExit(f'Cannot apply {label}: expected text not found')
    print(f'[APPLY] {label}')
    return text.replace(old, new, 1)


# 1) Archive-aware cache: preserve the full-history API contract while avoiding
# repeated Parquet reconstruction on each page refresh.
SERVICE.write_text(SERVICE_SOURCE)
print('[APPLY] archive-aware crypto history cache')

# 2) Render 1Y by default. All other range buttons continue to operate against
# the already-loaded full daily history payload.
history = HISTORY_JS.read_text()
history = replace_once(history, "let range = 'ALL';", "let range = '1Y';", '1Y default history range')
HISTORY_JS.write_text(history)

# 3) Make the 1Y button visually active on initial render instead of ALL.
template = TEMPLATE.read_text()
template = replace_once(
    template,
    '<button class="history-btn active" type="button" data-history-range="ALL">ALL</button><button class="history-btn" type="button" data-history-range="5Y">5Y</button><button class="history-btn" type="button" data-history-range="3Y">3Y</button><button class="history-btn" type="button" data-history-range="1Y">1Y</button>',
    '<button class="history-btn" type="button" data-history-range="ALL">ALL</button><button class="history-btn" type="button" data-history-range="5Y">5Y</button><button class="history-btn" type="button" data-history-range="3Y">3Y</button><button class="history-btn active" type="button" data-history-range="1Y">1Y</button>',
    '1Y active range button',
)

# 4) Insert an explicit correlation legend. The prior polish patch intentionally
# skipped this in some template states; use the stable heatmap container anchor.
legend = '''<div class="relationship-correlation-legend" aria-label="Correlation color scale"><span>−1 opposite</span><i class="negative"></i><i class="neutral"></i><i class="positive"></i><span>+1 together</span></div>'''
if 'relationship-correlation-legend' not in template:
    anchor = '<div id="relationship-heatmap" class="relationship-scroll" style="margin-top:14px"></div>'
    if anchor not in template:
        raise SystemExit('Cannot apply correlation color legend: heatmap anchor not found')
    template = template.replace(anchor, legend + anchor, 1)
    print('[APPLY] correlation color legend')
else:
    print('[SKIP] correlation color legend')

legend_css = '''
/* RELATIONSHIP CORRELATION LEGEND */
.relationship-correlation-legend{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:12px 0 2px;color:var(--muted);font-size:.74rem;font-weight:800}
.relationship-correlation-legend i{display:block;width:42px;height:9px;border-radius:99px;border:1px solid rgba(255,255,255,.08)}
.relationship-correlation-legend i.negative{background:linear-gradient(90deg,rgba(255,102,128,.82),rgba(255,102,128,.18))}
.relationship-correlation-legend i.neutral{background:rgba(145,166,194,.12)}
.relationship-correlation-legend i.positive{background:linear-gradient(90deg,rgba(57,227,161,.18),rgba(57,227,161,.82))}
'''
if '/* RELATIONSHIP CORRELATION LEGEND */' not in template:
    if '</style>' not in template:
        raise SystemExit('Cannot apply correlation legend styles: </style> not found')
    template = template.replace('</style>', legend_css + '\n</style>', 1)
    print('[APPLY] correlation legend styles')
else:
    print('[SKIP] correlation legend styles')

TEMPLATE.write_text(template)

print('Crypto Visual history performance + relationship legend patch complete.')
print('Default history render is now 1Y; full archive remains available through ALL/5Y/3Y.')
print('Historical cache invalidates automatically when Parquet archive files change.')
print('Presentation/cache only; models, journals, policies, and brokerage settings are unchanged.')
