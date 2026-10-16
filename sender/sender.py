#!/usr/bin/env python3
"""Opt-in telemetry sender for nfix-contribution.

Reads CLOSED trades from a local source (live tradesv3.sqlite or a
backtest-result zip), buckets them by ISO week x enter_tag x direction,
and POSTs ONLY the aggregates. Trade-level data never leaves this machine.

Usage:
  sender.py --db /path/to/tradesv3.sqlite --server http://VPS:8090 \
      --strategy NostalgiaForInfinityX8 --exchange bybit --market futures
  sender.py --backtest backtest-result-....zip --server ... (same flags)

The anonymous install id is created once and stored at
~/.nfix-contribution/install_id. Delete it any time to rotate identity.
"""
import argparse
import json
import sqlite3
import sys
import urllib.request
import uuid
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ID_FILE = Path.home() / ".nfix-contribution" / "install_id"


def install_id() -> str:
    ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ID_FILE.exists():
        return ID_FILE.read_text().strip()
    new = str(uuid.uuid4())
    ID_FILE.write_text(new)
    return new


def load_live(db_path: str) -> list:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT pair, is_short, enter_tag, open_date, close_date,"
        " close_profit, strategy FROM trades WHERE is_open = 0"
    ).fetchall()
    out = []
    for pair, is_short, tag, odt, cdt, profit, strategy in rows:
        if not cdt or profit is None:
            continue
        out.append({
            "pair": pair, "short": bool(is_short),
            "tag": (tag or "").strip(), "strategy": strategy,
            "open": datetime.fromisoformat(odt),
            "close": datetime.fromisoformat(cdt),
            "profit_pct": profit * 100,
        })
    return out


def load_backtest(zip_path: str) -> list:
    zz = zipfile.ZipFile(zip_path)
    names = [x for x in zz.namelist()
             if x.endswith(".json") and "config" not in x
             and "wallet" not in x and "market" not in x]
    d = json.loads(zz.read(names[0]))["strategy"]
    strat = next(iter(d))
    out = []
    for t in d[strat]["trades"]:
        out.append({
            "pair": t["pair"], "short": t.get("is_short", False),
            "tag": str(t.get("enter_tag", "")).strip(), "strategy": strat,
            "open": datetime.fromisoformat(str(t["open_date"])),
            "close": datetime.fromisoformat(str(t["close_date"])),
            "profit_pct": t["profit_ratio"] * 100,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--db", help="live tradesv3.sqlite (opened read-only)")
    src.add_argument("--backtest", help="backtest-result zip")
    ap.add_argument("--server", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--market", default="futures")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-fires", type=int, default=1,
                    help="skip buckets with fewer fires (default 1)")
    a = ap.parse_args()

    trades = load_live(a.db) if a.db else load_backtest(a.backtest)
    trades = [t for t in trades if t["strategy"] == a.strategy and t["tag"]]
    if not trades:
        print("no closed tagged trades found", file=sys.stderr)
        return 1

    buckets: dict = defaultdict(list)
    for t in trades:
        iso = t["close"].astimezone(timezone.utc).isocalendar()
        week = date.fromisocalendar(iso.year, iso.week, 1).isoformat()
        buckets[(week, t["tag"], "short" if t["short"] else "long")].append(t)

    iid = install_id()
    sent, skipped = 0, 0
    for (week, tag, direction), ts in sorted(buckets.items()):
        if len(ts) < a.min_fires:
            skipped += 1
            continue
        body = {
            "install_id": iid, "week": week,
            "strategy_version": a.strategy, "exchange": a.exchange,
            "market": a.market, "dry_run": a.dry_run,
            "tags": [{
                "tag": tag, "direction": direction,
                "fires": len(ts),
                "wins": sum(1 for t in ts if t["profit_pct"] >= 0),
                "avg_profit_pct": sum(t["profit_pct"] for t in ts) / len(ts),
                "avg_duration_min": sum(
                    (t["close"] - t["open"]).total_seconds() / 60
                    for t in ts) / len(ts),
            }],
        }
        req = urllib.request.Request(
            a.server.rstrip("/") + "/v1/pulse",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                assert r.status == 202, r.status
            sent += 1
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"submit failed for {tag}: {e}", file=sys.stderr)
    print(f"sent {sent} buckets, skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
