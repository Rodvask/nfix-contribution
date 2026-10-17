# Proposal: community trade telemetry for NostalgiaForInfinity

## The problem

NostalgiaForInfinity has dozens of entry signals refined over years of live trading,
but no signal performs the same on every exchange, in every regime, forever.
Today, when a tag starts failing — or when the crowd piles into the same pair at
the worst possible moment (blow-off tops) — each trader discovers it alone,
with their own money.

## The proposal

Build, together as a community, a telemetry system that pools **anonymous,
aggregate-only** trade outcomes so we can see which signals earn their keep:

- **Win rate per entry tag × exchange** — spot the tags that decay, per venue.
- **Weekly trends** — is a tag getting worse, or was it one bad week?
- **Shared evidence base** — real outcomes from many bots instead of anecdotes.

## What this data is for — and only for

This information would be used **exclusively for developing the project and
improving it dramatically**: sharper entries, better exits, smarter grinding and
rebuys — and ultimately higher profits for everyone running it. Nothing else.
No marketing, no third parties, no other purpose.

## Your privacy is non-negotiable

1. **100% optional.** Telemetry is off by default. Nothing ever leaves your
   machine unless you explicitly enable it — and the strategy works exactly
   the same with it off.
2. **Aggregates only.** Only weekly buckets would be transmitted
   (tag × exchange × week: fires, wins, average profit %, average duration) —
   never individual trades, stakes, balances, or keys.
3. **No identities.** The design stores a random install ID, never IP addresses,
   emails, or anything linkable to you.
4. **Anonymity threshold.** Groups with fewer than N distinct installs would be
   hidden from every public view — nobody could isolate "your" trades.
5. **Sensitive fields coarsened at the source**: profits rounded, durations
   bucketed, timestamps truncated, plus delayed, shuffled uploads so live
   positions can't be reconstructed.
6. **Open schema, open code.** Everything sent would be documented and auditable
   before anyone is asked to enable it.

## What we would build together

- A **community dashboard**: leaderboard per tag × exchange, worst-offenders
  list, tag detail with weekly trend charts.
- A shared backlog of **proven improvements**: decayed tags fixed or retired
  with evidence, grinding and rebuy logic tuned against real outcomes.
- Better profits for every participant, compounding with every contributor.

## How you could join (when it's ready)

1. Enable telemetry in your config (one flag — off unless you opt in).
2. Optionally share history — weekly aggregates only, generated locally.
3. Watch the dashboard; propose and vote on improvements backed by data.

Raw data would expire after 90 days; aggregates live on. There would be no
server to trust with your secrets — because it would never receive any.

**This is a proposal. Nothing is collecting data today. We build it together,
or we don't build it.**
