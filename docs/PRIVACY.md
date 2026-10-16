# Privacy design

## Threat model

The main risk is not a breach — the server holds nothing worth stealing —
but **linkage**: tying a bucket to a person, wallet, or IP.

## Mitigations

1. **Aggregates only, enforced by schema.** Pydantic uses `extra = "forbid"`,
   so a sender that (now or after a future change) includes prices, stakes,
   or balances gets HTTP 422 instead of silently storing them.
2. **No network identity.** Uvicorn runs with `--no-access-log`; the app never
   reads `X-Forwarded-For` or the peer address. There is no reverse proxy in
   the compose stack, so no other layer logs IPs either. If you add one,
   disable its access logs too.
3. **Unlinkable install ids.** Random UUID v4 generated locally, stored in
   `~/.nfix-contribution/install_id`. Rotatable by deleting the file.
   No account, email, or API key is ever requested.
4. **k-anonymity on read.** `/v1/leaderboard` suppresses any tag x exchange
   group with fewer than `MIN_INSTALLS` distinct installs (default 3).
5. **Retention.** Raw rows older than `RETENTION_DAYS` (default 90) are
   deleted on every write. Only the leaderboard (already anonymous) is
   effectively kept.
6. **Dry-run labelled.** Paper trades are flagged so they cannot pollute
   real-money statistics silently.

## Residual risks (honest list)

- A network observer (VPS provider, backbone) sees submission timing and
  source IP at the TCP layer; mitigations are Tor/VPN on the sender side.
  Content stays anonymous even then.
- Weekly buckets from a single-tag install could theoretically be matched
  against public leaderboard boasts ("I ran only tag 4 this week"). The
  `MIN_INSTALLS` gate and the absence of amounts make this low-value.
- This design deliberately cannot answer "what is user X holding right now"
  — that question is out of scope by construction.
