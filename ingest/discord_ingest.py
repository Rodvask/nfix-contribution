"""Discord ingestion for nfix-contribution v2.

Reads the channel where the daily nfi-report-<install_id>.json attachments land,
downloads them and normalises them into Postgres.

Usage
  python -m ingest.discord_ingest                 # poll forever (POLL_SECONDS)
  python -m ingest.discord_ingest --once          # one poll, then exit
  python -m ingest.discord_ingest --backfill      # walk the whole channel history once
  python -m ingest.discord_ingest --dir /path     # import plain .json files from a folder
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import re
import sys
import time
from typing import Any, Iterable, Optional

import psycopg
import requests

log = logging.getLogger("nfix.ingest")

DISCORD_API = "https://discord.com/api/v10"
REPORT_NAME = re.compile(r"^nfi-report-[A-Za-z0-9_-]+\.json$")
SCHEMA_PREFIX = "nfix8-report/"

DATABASE_URL = os.environ.get("DATABASE_URL", "")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "900") or 900)
INITIAL_LOOKBACK = int(os.environ.get("INITIAL_LOOKBACK", "200") or 200)
RAW_DIR = pathlib.Path(os.environ.get("RAW_DIR", "/data/raw"))
SCHEMA_PATH = pathlib.Path(os.environ.get("SCHEMA_PATH", "/app/db/schema.sql"))


# --------------------------------------------------------------------------- db


def connect() -> psycopg.Connection:
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL is required")
    return psycopg.connect(DATABASE_URL, autocommit=False)


def ensure_schema(conn: psycopg.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with conn.transaction():
        conn.execute(sql)


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    number = _num(value)
    return None if number is None else int(number)


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _orders(trade: dict) -> list:
    orders = (trade.get("orders") or {}).get("list") or []
    return [order for order in orders if isinstance(order, dict)]


def _grind_counts(trade: dict) -> tuple:
    payload = trade.get("orders") or {}
    counts = payload.get("counts_by_kind") or {}
    grinds = _int(payload.get("grinds"))
    derisks = _int(payload.get("derisks"))
    if grinds is None:
        grinds = _int(counts.get("grind")) or 0
    if derisks is None:
        derisks = _int(counts.get("derisk")) or 0
    return grinds, derisks


TRADE_COLUMNS = (
    "install_id", "trade_id", "pair", "side", "tag", "strategy", "strategy_version", "system_version",
    "leverage", "entries", "exits", "is_open", "opened_utc", "closed_utc", "open_rate", "close_rate",
    "amount", "stake", "max_stake", "fee_open", "fee_close", "funding", "mae_pct", "mfe_pct", "hours",
    "profit_pct", "profit_abs", "exit", "exit_detail", "age_hours", "unrealized_pct", "grinds", "derisks",
)

TRADE_SQL = """
INSERT INTO trade ({cols}, last_report_utc)
VALUES ({placeholders}, now())
ON CONFLICT (install_id, trade_id) DO UPDATE SET
  pair = EXCLUDED.pair, side = EXCLUDED.side, tag = EXCLUDED.tag,
  strategy = EXCLUDED.strategy, strategy_version = EXCLUDED.strategy_version,
  system_version = EXCLUDED.system_version, leverage = EXCLUDED.leverage,
  entries = EXCLUDED.entries, exits = EXCLUDED.exits, is_open = EXCLUDED.is_open,
  opened_utc = EXCLUDED.opened_utc, closed_utc = EXCLUDED.closed_utc,
  open_rate = EXCLUDED.open_rate, close_rate = EXCLUDED.close_rate,
  amount = EXCLUDED.amount, stake = EXCLUDED.stake, max_stake = EXCLUDED.max_stake,
  fee_open = EXCLUDED.fee_open, fee_close = EXCLUDED.fee_close, funding = EXCLUDED.funding,
  mae_pct = EXCLUDED.mae_pct, mfe_pct = EXCLUDED.mfe_pct, hours = EXCLUDED.hours,
  profit_pct = EXCLUDED.profit_pct, profit_abs = EXCLUDED.profit_abs,
  exit = EXCLUDED.exit, exit_detail = EXCLUDED.exit_detail,
  age_hours = EXCLUDED.age_hours, unrealized_pct = EXCLUDED.unrealized_pct,
  grinds = EXCLUDED.grinds, derisks = EXCLUDED.derisks, last_report_utc = now()
""".format(
    cols=", ".join(TRADE_COLUMNS),
    placeholders=", ".join(["%s"] * len(TRADE_COLUMNS)),
)

ORDER_SQL = """
INSERT INTO trade_order (install_id, trade_id, order_id, kind, tag, status, amount, filled,
  price, cost, fee_base, funding_fee, placed_utc, filled_utc)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (install_id, trade_id, order_id) DO UPDATE SET
  kind = EXCLUDED.kind, tag = EXCLUDED.tag, status = EXCLUDED.status,
  amount = EXCLUDED.amount, filled = EXCLUDED.filled, price = EXCLUDED.price,
  cost = EXCLUDED.cost, fee_base = EXCLUDED.fee_base, funding_fee = EXCLUDED.funding_fee,
  placed_utc = EXCLUDED.placed_utc, filled_utc = EXCLUDED.filled_utc
"""


def trade_values(install_id: str, trade: dict, is_open: bool) -> tuple:
    grinds, derisks = _grind_counts(trade)
    return (
        install_id,
        _int(trade.get("trade_id")),
        _text(trade.get("pair")) or "unknown",
        _text(trade.get("side")),
        _text(trade.get("tag")),
        _text(trade.get("strategy")),
        _text(trade.get("strategy_version")),
        _text(trade.get("system_version")),
        _num(trade.get("leverage")),
        _int(trade.get("entries")),
        _int(trade.get("exits")),
        bool(is_open),
        trade.get("opened_utc"),
        None if is_open else trade.get("closed_utc"),
        _num(trade.get("open_rate")),
        None if is_open else _num(trade.get("close_rate")),
        _num(trade.get("amount")),
        _num(trade.get("stake")),
        _num(trade.get("max_stake")),
        _num(trade.get("fee_open")),
        _num(trade.get("fee_close")),
        _num(trade.get("funding")),
        _num(trade.get("mae_pct")),
        _num(trade.get("mfe_pct")),
        None if is_open else _num(trade.get("hours")),
        None if is_open else _num(trade.get("profit_pct")),
        None if is_open else _num(trade.get("profit_abs")),
        None if is_open else _text(trade.get("exit")),
        None if is_open else _text(trade.get("exit_detail")),
        _num(trade.get("age_hours")) if is_open else None,
        _num(trade.get("unrealized_pct")) if is_open else None,
        grinds,
        derisks,
    )


def order_key(order: dict, index: int) -> str:
    order_id = order.get("order_id")
    if order_id is None or str(order_id).strip() == "":
        return "|".join(
            [
                str(index),
                str(order.get("kind") or ""),
                str(order.get("tag") or ""),
                str(order.get("placed_utc") or ""),
                str(order.get("amount") or ""),
            ]
        )
    return str(order_id)


def store_raw(payload: dict, raw: bytes) -> Optional[str]:
    install_id = _text(payload.get("install_id")) or "unknown"
    sent = _text(payload.get("sent_utc")) or ""
    day = sent[:10] if len(sent) >= 10 else "unknown"
    target = RAW_DIR / install_id / (day + ".json")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return str(target)
    except OSError as exc:
        log.warning("could not store raw report for %s: %s", install_id, exc)
        return None


def import_payload(conn: psycopg.Connection, payload: dict, raw: Optional[bytes] = None,
                   source: str = "unknown") -> str:
    """Normalise one report payload. Raises ValueError when it is not a valid report."""
    schema = _text(payload.get("schema")) or ""
    if not schema.startswith(SCHEMA_PREFIX):
        raise ValueError("unsupported schema " + repr(schema))
    install_id = _text(payload.get("install_id"))
    if not install_id:
        raise ValueError("missing install_id")
    sent_utc = _text(payload.get("sent_utc"))
    if not sent_utc:
        raise ValueError("missing sent_utc")
    sent_day = sent_utc[:10]

    raw_path = store_raw(payload, raw) if raw is not None else None
    closed = [t for t in (payload.get("closed_trades") or []) if isinstance(t, dict)]
    opened = [t for t in (payload.get("open_trades") or []) if isinstance(t, dict)]

    with conn.transaction():
        conn.execute("INSERT INTO install (install_id) VALUES (%s) ON CONFLICT DO NOTHING", (install_id,))
        row = conn.execute(
            """
            INSERT INTO report (install_id, sent_utc, sent_day, schema, strategy, strategy_version,
                                exchange, trading_mode, dry_run, window_days, summary, raw_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (install_id, sent_day) DO UPDATE SET
              sent_utc = EXCLUDED.sent_utc,
              schema = EXCLUDED.schema,
              strategy = EXCLUDED.strategy,
              strategy_version = EXCLUDED.strategy_version,
              exchange = EXCLUDED.exchange,
              trading_mode = EXCLUDED.trading_mode,
              dry_run = EXCLUDED.dry_run,
              window_days = EXCLUDED.window_days,
              summary = EXCLUDED.summary,
              raw_path = COALESCE(EXCLUDED.raw_path, report.raw_path),
              received_utc = now()
            RETURNING report_uid, (xmax = 0) AS is_new
            """,
            (
                install_id, sent_utc, sent_day, schema,
                _text(payload.get("strategy")), _text(payload.get("strategy_version")),
                _text(payload.get("exchange")), _text(payload.get("trading_mode")),
                bool(payload.get("dry_run")), _int(payload.get("window_days")),
                json.dumps(payload.get("summary") or {}), raw_path,
            ),
        ).fetchone()

        conn.execute(
            """
            UPDATE install SET
              last_seen_utc = now(),
              strategy = COALESCE(%s, strategy),
              strategy_version = COALESCE(%s, strategy_version),
              exchange = COALESCE(%s, exchange),
              trading_mode = COALESCE(%s, trading_mode),
              reports = reports + %s
            WHERE install_id = %s
            """,
            (
                _text(payload.get("strategy")), _text(payload.get("strategy_version")),
                _text(payload.get("exchange")), _text(payload.get("trading_mode")),
                1 if row[1] else 0, install_id,
            ),
        )

        # Older/newer payloads may omit the per-row strategy stamp: fall back to the report level.
        report_strategy = _text(payload.get("strategy"))
        report_version = _text(payload.get("strategy_version"))
        for trades, is_open in ((closed, False), (opened, True)):
            for trade in trades:
                if _int(trade.get("trade_id")) is None or not trade.get("opened_utc"):
                    log.debug("skipping trade without id/opened_utc in %s", install_id)
                    continue
                if report_version and not _text(trade.get("strategy_version")):
                    trade["strategy_version"] = report_version
                if report_strategy and not _text(trade.get("strategy")):
                    trade["strategy"] = report_strategy
                conn.execute(TRADE_SQL, trade_values(install_id, trade, is_open))
                for index, order in enumerate(_orders(trade)):
                    conn.execute(
                        ORDER_SQL,
                        (
                            install_id, _int(trade.get("trade_id")), order_key(order, index),
                            _text(order.get("kind")), _text(order.get("tag")), _text(order.get("status")),
                            _num(order.get("amount")), _num(order.get("filled")), _num(order.get("price")),
                            _num(order.get("cost")), _num(order.get("fee_base")), _num(order.get("funding_fee")),
                            order.get("placed_utc"), order.get("filled_utc"),
                        ),
                    )

    log.info(
        "imported report %s/%s from %s (%d closed, %d open)",
        install_id, sent_day, source, len(closed), len(opened),
    )
    return "imported"


# ---------------------------------------------------------------------- discord


def discord_get(url: str, params: Optional[dict] = None, tries: int = 5) -> Any:
    for attempt in range(tries):
        response = requests.get(
            url,
            headers={"Authorization": "Bot " + BOT_TOKEN, "User-Agent": "nfix-contribution/2"},
            params=params,
            timeout=30,
        )
        if response.status_code == 429:
            wait = float(response.json().get("retry_after", 2.0))
            log.warning("discord rate limited, waiting %.1fs", wait)
            time.sleep(min(wait, 30.0))
            continue
        if response.status_code >= 500 and attempt + 1 < tries:
            time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("discord request failed after retries")


def channel_messages(after: Optional[str] = None, before: Optional[str] = None, limit: int = 100) -> list:
    params: dict = {"limit": limit}
    if after:
        params["after"] = after
    if before:
        params["before"] = before
    data = discord_get(DISCORD_API + "/channels/" + CHANNEL_ID + "/messages", params)
    return data if isinstance(data, list) else []


def message_id_key(message: dict) -> int:
    try:
        return int(message.get("id", "0"))
    except (TypeError, ValueError):
        return 0


def seen(conn: psycopg.Connection, message_id: str, attachment_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ingest_seen WHERE source = 'discord' AND message_id = %s AND attachment_id = %s",
        (message_id, attachment_id or ""),
    ).fetchone()
    return row is not None


def mark_seen(conn: psycopg.Connection, message_id: str, attachment_id: str) -> None:
    conn.execute(
        "INSERT INTO ingest_seen (source, message_id, attachment_id) VALUES ('discord', %s, %s)"
        " ON CONFLICT DO NOTHING",
        (message_id, attachment_id or ""),
    )
    conn.commit()


def state_get(conn: psycopg.Connection, scope: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM ingest_state WHERE scope = %s", (scope,)).fetchone()
    return row[0] if row else None


def state_set(conn: psycopg.Connection, scope: str, value: str) -> None:
    conn.execute(
        "INSERT INTO ingest_state (scope, value, updated_utc) VALUES (%s, %s, now())"
        " ON CONFLICT (scope) DO UPDATE SET value = EXCLUDED.value, updated_utc = now()",
        (scope, value),
    )
    conn.commit()


def download(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"Authorization": "Bot " + BOT_TOKEN, "User-Agent": "nfix-contribution/2"},
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def process_messages(conn: psycopg.Connection, messages: Iterable) -> tuple:
    seen_n = 0
    imported = 0
    skipped = 0
    failed = 0
    for message in sorted(messages, key=message_id_key):
        for attachment in message.get("attachments") or []:
            name = attachment.get("filename") or ""
            if not REPORT_NAME.match(name):
                continue
            seen_n += 1
            message_id = str(message.get("id"))
            attachment_id = str(attachment.get("id") or "")
            if seen(conn, message_id, attachment_id):
                skipped += 1
                continue
            try:
                payload_bytes = download(attachment.get("url") or "")
                payload = json.loads(payload_bytes)
                import_payload(conn, payload, payload_bytes, source="discord:" + message_id)
                mark_seen(conn, message_id, attachment_id)
                imported += 1
            except Exception as exc:
                failed += 1
                log.warning("failed to ingest %s (message %s): %s", name, message_id, exc)
                conn.rollback()
    return seen_n, imported, skipped, failed


def poll_once(conn: psycopg.Connection, backfill: bool = False) -> tuple:
    last = None if backfill else state_get(conn, "discord_last_message")
    messages = []
    if last:
        after = last
        while True:
            batch = channel_messages(after=after)
            messages.extend(batch)
            if len(batch) < 100:
                break
            after = str(max(message_id_key(m) for m in batch))
    else:
        before = None
        while len(messages) < max(INITIAL_LOOKBACK, 100):
            batch = channel_messages(before=before, limit=100)
            if not batch:
                break
            messages.extend(batch)
            before = str(min(message_id_key(m) for m in batch))
            if len(batch) < 100:
                break
    totals = process_messages(conn, messages)
    if messages:
        newest = max(message_id_key(m) for m in messages)
        if last is None or newest > message_id_key({"id": last}):
            state_set(conn, "discord_last_message", str(newest))
    conn.execute(
        "INSERT INTO ingest_log (source, seen, imported, skipped, failed, note) VALUES (%s, %s, %s, %s, %s, %s)",
        ("discord-backfill" if backfill else "discord", totals[0], totals[1], totals[2], totals[3], "last=" + str(last)),
    )
    conn.commit()
    return totals


def import_dir(conn: psycopg.Connection, directory: pathlib.Path) -> tuple:
    files = sorted(p for p in directory.glob("*.json") if p.is_file())
    seen_n = imported = failed = 0
    for path in files:
        seen_n += 1
        try:
            raw = path.read_bytes()
            import_payload(conn, json.loads(raw), raw, source="dir:" + path.name)
            imported += 1
        except Exception as exc:
            failed += 1
            log.warning("failed to import %s: %s", path, exc)
            conn.rollback()
    conn.execute(
        "INSERT INTO ingest_log (source, seen, imported, skipped, failed, note) VALUES (%s, %s, %s, %s, %s, %s)",
        ("dir", seen_n, imported, 0, failed, str(directory)),
    )
    conn.commit()
    return seen_n, imported, 0, failed


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="nfix-contribution discord ingestion")
    parser.add_argument("--once", action="store_true", help="run a single poll and exit")
    parser.add_argument("--backfill", action="store_true", help="walk the channel history once")
    parser.add_argument("--dir", type=pathlib.Path, help="import plain .json reports from a folder")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    conn = connect()
    ensure_schema(conn)

    if args.dir:
        log.info("dir import %s -> %s", args.dir, import_dir(conn, args.dir))
        return 0

    if not BOT_TOKEN or not CHANNEL_ID:
        log.warning("DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID are required to read the channel")
        if args.once:
            return 2
        while True:
            time.sleep(POLL_SECONDS)

    while True:
        try:
            log.info("poll %s", poll_once(conn, backfill=args.backfill))
            args.backfill = False
        except Exception as exc:
            log.warning("poll failed: %s", exc)
            try:
                conn.rollback()
            except Exception:
                conn = connect()
        if args.once:
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
