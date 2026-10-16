# nfix-contribution

Anonymous community trade telemetry for NostalgiaForInfinity.
The server collects **pre-aggregated buckets only** — one row per
install/week/strategy/tag. Individual trades never leave the sender's machine.

## How it works

1. The bot owner runs `sender/sender.py` (opt-in, manual or cron). It reads
   **closed** trades from the local live DB or a backtest zip, buckets them by
   ISO week x enter_tag x direction, and POSTs the aggregates.
2. The API stores buckets in Postgres. Raw rows older than `RETENTION_DAYS`
   are deleted on write.
3. Contributors read `GET /v1/leaderboard` (win rate per tag x exchange).
   Groups with fewer than `MIN_INSTALLS` distinct installs are suppressed.

## What is sent (allowlist)

`install_id` (random local UUID), `week`, `strategy_version`, `exchange`,
`market`, `dry_run`, and per tag: `fires, wins, avg_profit_pct,
avg_duration_min`. The schema **rejects** any trade-level field
(prices, stakes, balances) with HTTP 422.

## What is never collected

No API keys, no stakes, no balances, no IPs (the app emits no access logs
and never reads client addresses), no emails, no accounts. See
[docs/PRIVACY.md](docs/PRIVACY.md).

## Run it

```bash
cp .env.example .env        # set POSTGRES_PASSWORD
docker compose up -d --build
curl localhost:8090/health  # {"ok": true}
```

## Send telemetry (opt-in, from any machine)

```bash
python3 sender/sender.py --db user_data/tradesv3.sqlite \
  --server http://YOUR-VPS:8090 \
  --strategy NostalgiaForInfinityX8 --exchange bybit --market futures
```

Rotate identity any time: `rm ~/.nfix-contribution/install_id`.

## Read the aggregate

```bash
curl "http://YOUR-VPS:8090/v1/leaderboard?strategy_version=NostalgiaForInfinityX8&weeks=12"
```
