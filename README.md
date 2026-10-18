# nfix-contribution v2

Anonymous, opt-in telemetry for [NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) X8: one daily
report per installation, aggregated here so the strategy can be tuned with data from real bots instead of opinions.

Everything in this repo runs with `docker compose up`. No build step, no JavaScript dependencies, no external requests
from the dashboard.

## What a report contains (and what it never contains)

The bot sends one JSON file per day (schema `nfix8-report/2`) built from a strict allowlist in the strategy itself:

- `install_id` — random id created once per installation (`uuid4()`, stored in `user_data/nfi-anonymous-report.json`).
- strategy/system version, exchange, trading mode, dry-run flag, window days.
- `summary` — closed/open counts, win rate, average/median/best/worst %, absolute profit, hours, grinds, derisks, plus
  `by_tag` and `by_exit` breakdowns.
- `closed_trades` / `open_trades` — per trade: pair, side, tag, leverage, entries, exits, timestamps, rates, amount,
  stake, max stake, fees, funding, MAE, MFE, hours, profit %, profit abs, exit engine + exit reason, and the **order list**
  with the kind of every order (`entry`, `grind`, `derisk`, `rebuy`, `exit`, ...).

Never sent or stored here: API keys, secrets, IP addresses, hostnames, absolute balances, wallet sizes, order exchange ids,
or anything else that identifies a person, a machine or an account. Trade pairs and timestamps are what makes the data
useful, so they are included — if that is too much for you, do not enable the report.

## Privacy model of the dashboard

- Aggregates (tags, pairs, exits, grind buckets, versions) are public.
- Per-trade detail (`/api/trades`, `/api/worst`, `/api/trade/...`) requires `DASHBOARD_TOKEN`; unset means those
  endpoints are disabled (403).
- `MIN_INSTALLS` (default 3) hides aggregate rows that come from fewer installations, so a single bot cannot be singled
  out in the tags/pairs tables.
- Access logs are disabled (`--no-access-log`), the API never writes client addresses anywhere, and no analytics,
  fonts or CDNs are loaded by the page.

## Layout

```
db/schema.sql              tables: install, report, trade, trade_order, ingest_seen, ingest_state, ingest_log
ingest/discord_ingest.py   reads the Discord channel (or a local folder) and imports reports into Postgres
api/app.py                 read-only FastAPI endpoints + static dashboard
web/                       dashboard (plain HTML/CSS/JS, fetches its own /api/*)
tests/                     unit tests and an end-to-end smoke test with generated fixtures
```

## Deploy

```bash
cp .env.example .env          # set POSTGRES_PASSWORD, and DASHBOARD_TOKEN if you want the detail views
docker compose up -d db       # postgres
docker compose up -d api      # http://localhost:8090
docker compose up -d ingest   # discord reader (needs DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID)
```

### Discord ingestion

1. Create an application at <https://discord.com/developers/applications> → Bot → *Reset Token*.
   The Message Content intent is **not** required: attachments are enough.
2. Invite the bot to the server with *View Channel* + *Read Message History* for the report channel.
3. Put the token and the channel id in `.env` (`DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`) and start the `ingest` service.
4. First run walks back `INITIAL_LOOKBACK` messages (100 per request); after that it polls every `POLL_SECONDS`.
   Every downloaded file is stored under `data/raw/<install_id>/<day>.json` and re-imports are idempotent
   (unique on `install_id + sent_day`, upsert on `install_id + trade_id`).

### Import without Discord

```bash
python3 tests/fixtures/make_fixture.py data/fixtures     # writes three reports + one broken file
docker compose run --rm ingest python -m ingest.discord_ingest --dir /data/fixtures
```

## Dashboard

- **Resumen** — closed trades, win rate, average/median profit, sum %, absolute profit, hours, MAE/MFE, installs, open
  positions with unrealized %, plus a daily activity trend.
- **Tags** — ranking (sortable, click a row for pairs / exit reasons / order kinds / weekly trend).
- **Grind / derisk** — the question that matters: trades grouped by `plain` / `grind only` / `derisk only` /
  `grind+derisk` with win rate, average %, p10, hours, MAE/MFE, average entries and stake growth, plus order-kind counts.
- **Versiones** — strategy/system version comparison and the list of reporting installations (masked ids).
- **Pares**, **Salidas** — per pair and per exit engine (engine name is normalised: `exit_long_normal_w_0 ( 200 )` →
  `exit_long_normal`).
- **Trades**, **Peores** — paged trade explorer and the worst trades, with the full order list of any trade
  (needs `DASHBOARD_TOKEN` in the header field; it is kept in `localStorage`).

## API

| endpoint | notes |
| --- | --- |
| `GET /healthz` | db reachable? |
| `GET /api/meta` | counts, versions, last ingest, k-anonymity floor |
| `GET /api/overview` | totals, open positions, daily series |
| `GET /api/tags`, `/api/tag/{tag}` | ranking and per-tag detail |
| `GET /api/grind` | grind/derisk buckets, order kinds, per-tag grind pressure, weekly trend |
| `GET /api/versions`, `/api/pairs`, `/api/exits` | comparisons |
| `GET /api/trades`, `/api/worst`, `/api/trade/{install_id}/{trade_id}` | token required |

Common query params: `days`, `version`, `system_version`, `side`, `exchange`, `tag`, `pair`.
Sorting for `/api/tags`: `sort=n|wr|avg|med|sum|hours|mae|worst`.

## Tests

```bash
python3 -m pytest tests -q          # pure functions: allowlist mapping, order keys, payload validation
bash tests/smoke.sh                 # brings the stack up, imports fixtures, hits every endpoint
```
