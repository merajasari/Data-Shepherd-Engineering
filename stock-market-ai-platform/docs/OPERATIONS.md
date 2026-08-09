# Stock Market AI Platform — Operations Runbook

## Purpose

This runbook documents the current Android/Termux operating model for the Stock Market AI Platform.

The production-style local stack consists of:

```text
runsvdir
  ├── crond
  └── stock-market-ai
        ├── Tiingo IEX WebSocket
        └── Flask web application
```

The historical refresh pipeline is scheduled independently through cron and protected from overlapping runs with `flock`.

## Service Status

```bash
sv status crond
sv status stock-market-ai
```

Healthy services report `run:`.

## Restart the Platform

```bash
sv restart stock-market-ai
```

This restarts both the WebSocket and Flask children through the supervised service.

## Stop / Start

```bash
sv down stock-market-ai
sv up stock-market-ai
```

For cron:

```bash
sv down crond
sv up crond
```

## Verify the Dashboard

```bash
curl -I http://127.0.0.1:5000
```

Expected result:

```text
HTTP/1.1 200 OK
```

The local dashboard is available at:

```text
http://127.0.0.1:5000
```

When binding to `0.0.0.0`, Flask may also report the device's LAN address for access from another device on the same network.

## Live Feed Checks

```bash
tail -20 logs/iex_stream.log
cat data/live/latest_quotes.json
```

A healthy closed-market stream may show:

- successful WebSocket connection
- successful subscription
- heartbeats
- no current quote values

That is normal. The dashboard falls back to latest EOD pricing.

## Flask Checks

```bash
tail -20 logs/webapp.log
curl -I http://127.0.0.1:5000
```

If Flask reports `Address already in use`, identify and stop the stale Python process before restarting the supervised service.

## Scheduled Refresh

Current cron schedule:

```text
5 * * * *
```

The job runs at minute 05 of every hour.

Check the installed crontab:

```bash
crontab -l
```

The job uses `flock -n` to prevent overlapping refresh processes.

## Refresh Pipeline Behavior

`refresh_pipeline.sh` first performs a sentinel EOD freshness check.

```text
newer EOD timestamp absent -> exit cleanly
newer EOD timestamp present -> full pipeline
```

Full pipeline:

```text
Tiingo ingestion
  -> Silver
  -> Gold
  -> Features
  -> train all models
```

This is intentionally separate from the continuously running live IEX WebSocket.

## Rate Limits

Repeated manual full-universe requests can trigger Tiingo HTTP 429 responses. Avoid repeatedly launching full ingestion during the same rate-limit window.

The sentinel design exists specifically to minimize unnecessary calls.

## Manual Manager

`run_platform.sh` can manage the Flask and IEX processes manually when runit is not being used:

```bash
./run_platform.sh start
./run_platform.sh stop
./run_platform.sh status
./run_platform.sh restart
```

Do not run the manual manager on top of an already active runit-managed `stock-market-ai` service, because that can create duplicate WebSocket processes or a port-5000 conflict.

## Boot Persistence

The Google Play Termux build uses a boot script under:

```text
~/.termux/boot/
```

The configured script starts the Termux service supervisor. Both `crond` and `stock-market-ai` are enabled services.

After reboot, verify:

```bash
pgrep -a runsvdir
sv status crond
sv status stock-market-ai
curl -I http://127.0.0.1:5000
```

The reboot recovery path has been tested successfully.

## Runtime Files

Do not commit runtime state:

```text
data/live/
logs/
run/
*.lock
```

Generated market data and model artifacts are also ignored.

## Secret Handling

Never commit:

```text
.env
API tokens
credentials
secret-bearing logs
```

If an API token is exposed in terminal output, screenshots, logs, or public messages, rotate it with the data provider and update the local `.env` file.

## Troubleshooting Sequence

For a general platform issue, use this order:

```bash
sv status stock-market-ai
sv status crond
curl -I http://127.0.0.1:5000
tail -40 logs/webapp.log
tail -40 logs/iex_stream.log
crontab -l
```

This separates web-service failures, live-feed failures, and scheduled-pipeline failures before changing code.
