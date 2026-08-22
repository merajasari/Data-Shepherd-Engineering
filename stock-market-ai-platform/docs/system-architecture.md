# Data Shepherd Engineering — System Architecture

This document describes the complete repository and runtime architecture as of
2026-08-22. It separates authoritative data flows, research-only workflows,
frozen/forward evaluation, presentation, and external services.

```mermaid
flowchart TB
    USERS["Members and public visitors"]
    MAC["macOS host<br/>LaunchAgents + virtualenv"]
    EDGE["Cloudflare Tunnel<br/>HTTPS edge"]

    subgraph SOURCES["External data and platform services"]
        TIINGO["Tiingo REST<br/>daily EOD stocks"]
        IEX["Tiingo IEX WebSocket<br/>live stock quotes"]
        COINBASE["Coinbase WebSocket + REST<br/>crypto ticks and closed 15m bars"]
        KRAKEN["Kraken archives<br/>historical crypto research"]
        OPENAI["OpenAI API<br/>Shepherd AI answers"]
        RESEND["Resend<br/>verification email"]
    end

    subgraph STOCK_DATA["Stock data engineering"]
        QUOTA["Quota-aware incremental refresh<br/>rolling 60-minute ledger"]
        BRONZE["Bronze<br/>raw per-symbol parquet"]
        SILVER["Silver<br/>validated and standardized"]
        GOLD["Gold<br/>analytics-ready market data"]
        FEATURES["Feature layer<br/>Pandas or isolated Spark backend"]
        CONVERGE["101-symbol convergence<br/>common completed EOD session"]
        LIVE_STOCK["Live IEX state<br/>quote cache + stream health"]
    end

    subgraph STOCK_INTELLIGENCE["Stock intelligence"]
        LEGACY["Historical comparisons<br/>V4 and V5 artifacts"]
        V8INF["Frozen V8 inference<br/>100 ranked candidates"]
        V8GATE["V8 EOD guard<br/>contract + freshness + completeness"]
        V8RUN["V8 paper / holdout runner<br/>append-only evidence"]
        V10DEV["V10 research<br/>source panel + phases 1–4"]
        V10TUNE["V10 automatic tuning<br/>Cycle 1 + Cycle 2"]
        V10CONF["V10 prospective confirmation<br/>locked challenger vs V8"]
        LAB["Additional research laboratory<br/>V11 discovery; non-production"]
    end

    subgraph CRYPTO_DATA["Crypto data engineering"]
        TICKER["Continuous ticker stream<br/>25 USD products"]
        RECON["Closed 15-minute reconciliation<br/>authoritative REST correction"]
        ARCHIVE["Canonical 15-minute archive<br/>no synthetic candles"]
        CRYPTO_STATE["Live/reconciled state<br/>quotes, freshness, readiness"]
    end

    subgraph CRYPTO_INTELLIGENCE["Crypto intelligence"]
        SHARED["Shared Crypto 15m research<br/>V1–V4 research generations"]
        CV2["Frozen Crypto 15m V2<br/>BTC / ALT / CASH confirm_2"]
        XRP["Dedicated XRP research<br/>separate gap-aware lineage"]
        FORWARD["Shadow forward services<br/>state + journals, no orders"]
    end

    subgraph STORAGE["Local materialized state"]
        DATA["data/<br/>bronze, silver, gold, features"]
        MODELS["data/model/<br/>contracts, models, metrics, evidence"]
        LIVE["data/live/<br/>rankings, streams, journals, statuses"]
        GENERATED["webapp/static/generated/<br/>read-only dashboard artifacts"]
        ACCOUNTS["Account store + sessions<br/>credentials never in Git"]
        LOGS["logs/<br/>Gunicorn and LaunchAgent health"]
    end

    subgraph WEB["Application and presentation"]
        GUNICORN["Gunicorn<br/>Flask webapp on 127.0.0.1:5001"]
        SERVICES["Service layer<br/>market, prediction, paper, history, health"]
        API["Authenticated + public APIs<br/>rate limits and payload guards"]
        UI["Landing, stock, crypto dashboards<br/>HTML + CSS + JavaScript"]
        ASSISTANT["Site-wide Shepherd AI<br/>page-aware same-origin endpoint"]
    end

    subgraph OPERATIONS["Scheduling, safety, and deployment"]
        LAUNCHD["macOS LaunchAgents<br/>stream, refresh, reconcile, forward, web"]
        HEALTH["Health/readiness checks<br/>fail closed on stale or incomplete data"]
        LOCKS["Process and orchestration locks<br/>prevent concurrent evidence writes"]
        SAFETY["Research safeguards<br/>purging, frozen boundaries, no brokerage orders"]
        TESTS["Unit, contract, parity,<br/>holdout and integration tests"]
        GIT["GitHub<br/>source, branches, PRs, history"]
    end

    TIINGO --> QUOTA --> BRONZE --> SILVER --> GOLD --> FEATURES --> CONVERGE
    IEX --> LIVE_STOCK
    FEATURES --> DATA
    LIVE_STOCK --> LIVE
    CONVERGE --> V8INF --> V8GATE --> V8RUN
    FEATURES --> V10DEV --> V10TUNE --> V10CONF
    FEATURES --> LAB
    LEGACY --> GENERATED
    V8INF --> LIVE
    V8RUN --> MODELS
    V10DEV --> MODELS
    V10TUNE --> MODELS
    V10CONF --> GENERATED

    COINBASE --> TICKER --> CRYPTO_STATE
    COINBASE --> RECON --> ARCHIVE
    KRAKEN --> ARCHIVE
    ARCHIVE --> SHARED
    ARCHIVE --> XRP
    SHARED --> CV2 --> FORWARD
    XRP --> FORWARD
    CRYPTO_STATE --> FORWARD
    ARCHIVE --> DATA
    FORWARD --> LIVE
    FORWARD --> MODELS

    DATA --> SERVICES
    MODELS --> SERVICES
    LIVE --> SERVICES
    GENERATED --> SERVICES
    ACCOUNTS --> GUNICORN
    SERVICES --> API --> UI
    GUNICORN --> SERVICES
    UI --> ASSISTANT --> OPENAI
    USERS --> EDGE --> GUNICORN
    GUNICORN --> RESEND

    MAC --> LAUNCHD
    LAUNCHD --> QUOTA
    LAUNCHD --> LIVE_STOCK
    LAUNCHD --> TICKER
    LAUNCHD --> RECON
    LAUNCHD --> FORWARD
    LAUNCHD --> GUNICORN
    LAUNCHD --> LOGS
    HEALTH --> V8GATE
    LOCKS --> V8RUN
    SAFETY --> V8RUN
    SAFETY --> V10CONF
    SAFETY --> FORWARD
    TESTS --> GIT
    GIT --> MAC
```

## Operational paths

| Path | Trigger | Main flow | Output | Safety boundary |
|---|---|---|---|---|
| Stock EOD | Quota-aware LaunchAgent | Tiingo → Bronze → Silver → Gold → Features → V8 inference | Rankings, readiness and comparison artifacts | All symbols must converge; guard fails closed |
| Stock live | KeepAlive LaunchAgent | IEX WebSocket → live cache → web services | Live quotes and stream-health panels | Latest EOD fallback when live data is unavailable |
| V8 evaluation | EOD orchestrator / backup scheduler | Guard → frozen-contract verification → append-only runner | Paper/holdout status and journal evidence | No pre-boundary evidence; shared lock; no orders |
| V10 research | Explicit research commands | Source panel → phases → automatic tuning Cycles 1/2 | Development metrics and candidate registries | Development-only; prospective confirmation and formal holdout remain separate |
| Crypto live | KeepAlive LaunchAgents | Coinbase stream + REST reconciliation | Live tickers and authoritative closed 15m bars | Missing candles are not synthesized |
| Crypto forward | Scheduled shadow services | Reconciled archive → frozen policy → state/journal | BTC/ALT/CASH and XRP shadow state | Hash/policy verification; no brokerage execution |
| Web | KeepAlive LaunchAgent | Gunicorn → Flask services → APIs/templates | Member dashboards and public landing pages | Secure cookies, authentication, rate limits |
| Shepherd AI | User question | Visible page context → Flask endpoint → OpenAI | Plain-text site explanation | Server-side key; bounded context; no financial advice or order execution |

## Persistence boundaries

- **Source control:** code, tests, documentation, templates, static application assets.
- **Materialized data:** Bronze/Silver/Gold/features, canonical crypto history, and live state.
- **Research evidence:** model contracts, metrics, manifests, frozen specifications, and journals.
- **Published presentation:** generated JSON consumed by dashboard JavaScript.
- **Secrets:** local environment only; API keys and credentials are excluded from Git.
- **Historical lineage:** retired-generation artifacts may remain as provenance but cannot
  be relabelled as new evidence or used to reopen a frozen selection decision.
