# nfix-contribution: community trade telemetry for NostalgiaForInfinity

## The problem

NostalgiaForInfinity has dozens of entry signals refined over years of live trading,
but no signal performs the same on every exchange, in every regime, forever.
Today, when a tag starts failing — or when the crowd piles into the same pair at
the worst possible moment (NXPC-style blow-off tops) — each trader discovers it
alone, with their own money.

## The idea

Pool **anonymous, aggregate-only** trade outcomes from the community so everyone
can see which signals earn their keep:

- **Win rate per entry tag × exchange** — spot the tags that decay, per venue.
- **Weekly trends** — is a tag getting worse, or was it one bad week?
- **Live crowd pulse (24h)** — how many bots are entering the same tag × pair
  *right now*, so your bot can skip overcrowded entries instead of joining them.

## Privacy by design (non-negotiable)

1. **Opt-in, off by default.** Nothing leaves your machine unless you enable it.
2. **Aggregates only.** Your bot transmits weekly buckets
   (tag × exchange × week: fires, wins, average profit %, average duration) —
   never individual trades, stakes, balances, or keys.
3. **No identities.** The server stores a random install UUID, never IP addresses,
   emails, or anything linkable to you.
4. **Anonymity threshold.** Groups with fewer than N distinct installs are
   suppressed from every public view — nobody can isolate "your" trades.
5. **Sensitive fields are coarsened at the source**: profit rounded to 0.5%,
   durations to 5 minutes, timestamps truncated to the hour, plus a 15-minute
   hold-back and shuffled upload order so live positions can't be reconstructed.
6. **Open schema, open code.** Everything sent is documented and auditable;
   the dashboard shows only what the API serves.

## What contributors get

- A **live dashboard**: leaderboard per tag × exchange, worst-offenders list,
  click-through tag detail with weekly trend charts, and freshness metadata.
- A **crowd protection** for the strategy itself: when the pulse shows too many
  bots entering the same tag × pair, entries are skipped (fail-open — any
  missing or stale data simply allows the trade).
- Better signals for everyone: decayed tags get fixed or retired with evidence,
  not anecdotes.

## Status (October 2026)

- Ingest server + Postgres + dashboard live; weekly sender script validated
  against real live-trading databases.
- Strategy integration on an experimental branch: opt-in event reporting,
  hourly retry, crowd protection — verified with live dry-run fills and
  bit-identical backtests (reporting is dead code in backtests).
- First community data flowing (Binance/Bybit, X7 + X8); threshold currently
  lowered for preview, raised to 3+ installs for public views.

## How to join

1. Update to a build with telemetry support.
2. Enable it in your config (one flag + server URL + strategy label).
3. Optionally backfill history with the sender script — weekly aggregates only.
4. Watch the dashboard; propose tag fixes with data attached.

Raw data expires after 90 days; aggregates live on. No server to trust with
your secrets — because it never receives any.
