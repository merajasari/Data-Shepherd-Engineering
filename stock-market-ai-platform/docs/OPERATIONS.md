# Stock Market AI Platform — Operations Runbook

## Purpose

This runbook documents the current public Android/Termux production-style deployment for the Stock Market AI Platform.

Public site:

```text
https://datashepherdengineering.com
https://www.datashepherdengineering.com
```

## Production Service Layout

```text
runsvdir
  ├── crond
  ├── stock-market-ai
  │     └── Gunicorn -> Flask
  ├── iex-stream
  │     └── Tiingo IEX WebSocket
  └── cloudflared
        └── named tunnel: data-shepherd
```

The historical EOD refresh pipeline runs through cron and remains separate from the continuously running live stream and public web path.

## Service Status

```bash
sv status crond
sv status stock-market-ai
sv status iex-stream
sv status cloudflared
```

Healthy services report `run:`.

## Restart Services

```bash
sv restart stock-market-ai
sv restart iex-stream
sv restart cloudflared
```

Cron can be restarted with:

```bash
sv restart crond
```

## Local Web Verification

```bash
curl -I http://127.0.0.1:5000
```

Expected server header:

```text
Server: gunicorn
```

Gunicorn currently binds only to loopback:

```text
127.0.0.1:5000
```

The origin port is not intended to be exposed directly to the Internet.

## Public Verification

```bash
curl -I https://datashepherdengineering.com
curl -I https://www.datashepherdengineering.com
curl -s https://datashepherdengineering.com/health
```

A healthy public response should return HTTP 200 through Cloudflare. The health endpoint should include:

```json
{"status":"healthy"}
```

`live_symbols: 0` can be normal outside active market periods when no current IEX quote is cached.

## Gunicorn

The `stock-market-ai` runit service runs Gunicorn rather than Flask/Werkzeug's development server.

Conceptual command:

```bash
gunicorn \
  --bind 127.0.0.1:5000 \
  --workers 2 \
  --timeout 120 \
  webapp.app:app
```

Logs:

```text
logs/gunicorn-access.log
logs/gunicorn-error.log
```

## Live IEX Service

The Tiingo IEX stream is now isolated in its own runit service:

```text
iex-stream
```

Useful checks:

```bash
sv status iex-stream
ps -ef | grep '[i]ex_stream.py'
tail -40 logs/iex_stream.log
cat data/live/latest_quotes.json
```

The UI falls back to latest EOD pricing when live data is unavailable.

## Cloudflare Tunnel

The public site is delivered through a named Cloudflare Tunnel:

```text
data-shepherd
```

Request flow:

```text
Cloudflare edge
  -> encrypted outbound tunnel
  -> 127.0.0.1:5000
  -> Gunicorn
  -> Flask
```

Useful checks:

```bash
sv status cloudflared
cloudflared tunnel list
```

Tunnel config is stored locally under:

```text
~/.cloudflared/config.yml
```

Credential files such as `cert.pem` and tunnel JSON files are secrets and must never be committed.

## DNS / Domain

The domain is registered with Namecheap and uses Cloudflare nameservers.

The web hostnames are routed to the named tunnel rather than to a public origin IP:

```text
datashepherdengineering.com
www.datashepherdengineering.com
```

Cloudflare provides public HTTPS at the edge.

## Scheduled Historical Refresh

Current cron cadence:

```text
5 * * * *
```

Check it with:

```bash
crontab -l
```

The refresh job uses `flock -n` to prevent overlap.

## Refresh Pipeline Behavior

`refresh_pipeline.sh` performs an EOD freshness check before rebuilding the full pipeline.

```text
no newer EOD timestamp -> exit cleanly
newer EOD timestamp    -> full refresh
```

Full refresh:

```text
Tiingo historical ingestion
  -> Silver
  -> Gold
  -> Features
  -> train all 26 models
```

This is intentionally independent of the live IEX WebSocket.

## Rate Limits

Repeated manual full-universe Tiingo requests can return HTTP 429. Avoid unnecessary back-to-back full refreshes. The sentinel design exists to minimize API usage.

## Forecast Verification

The new five-day market-wide forecast endpoint covers all 26 symbols:

```bash
curl -s http://127.0.0.1:5000/api/forecast
```

Expected metadata includes:

```text
symbol_count: 26
available_count: 26
```

The chart is a directional trend visualization, not a future price target.

## Boot Persistence

The Termux boot script starts `runsvdir`. The following services are enabled:

```text
crond
stock-market-ai
iex-stream
cloudflared
```

After reboot, verify:

```bash
pgrep -a runsvdir
sv status crond
sv status stock-market-ai
sv status iex-stream
sv status cloudflared
curl -I https://datashepherdengineering.com
```

## Runtime Files

Do not commit:

```text
data/live/
logs/
run/
*.lock
models/*.pkl
```

## Secrets

Never commit:

```text
.env
API tokens
Cloudflare cert.pem
Cloudflare tunnel credential JSON
payment/account credentials
secret-bearing logs
```

If a provider token is exposed, rotate it and update the local `.env`.

## Troubleshooting Order

For a public-site issue:

```bash
sv status stock-market-ai
curl -I http://127.0.0.1:5000
sv status cloudflared
curl -I https://datashepherdengineering.com
tail -40 logs/gunicorn-error.log
```

For live-market issues:

```bash
sv status iex-stream
tail -40 logs/iex_stream.log
cat data/live/latest_quotes.json
```

For scheduled historical issues:

```bash
sv status crond
crontab -l
tail -40 logs/cron.log
tail -40 logs/refresh_pipeline.log
```

This ordering separates origin-server failures, tunnel failures, live-feed failures, and scheduled-pipeline failures before changing code.
