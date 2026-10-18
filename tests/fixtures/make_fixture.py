"""Generate a handful of realistic anonymous reports (nfix8-report/2) for local testing."""
import json
import pathlib
import sys

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data/fixtures")


def order(order_id, kind, tag, side, amount, price, placed, filled_ts, filled=None, cost=None):
    filled = amount if filled is None else filled
    return {
        "order_id": order_id,
        "kind": kind,
        "tag": tag,
        "status": "closed" if filled > 0 else "open",
        "is_entry": side == "entry",
        "amount": amount,
        "filled": filled,
        "price": price,
        "cost": cost if cost is not None else round(amount * price, 4),
        "fee_base": round(amount * price * 0.0005, 8),
        "funding_fee": 0.0,
        "placed_utc": placed,
        "filled_utc": filled_ts,
    }


def orders_block(rows):
    entries = {}
    exits = {}
    counts = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
        (entries if row["is_entry"] else exits)[row["tag"]] = (
            (entries if row["is_entry"] else exits).get(row["tag"], 0) + 1
        )
    return {
        "entries_by_tag": entries,
        "exits_by_tag": exits,
        "counts_by_kind": counts,
        "grinds": sum(1 for r in rows if r["kind"] == "grind" and r["filled"] > 0),
        "derisks": sum(1 for r in rows if r["kind"] == "derisk" and r["filled"] > 0),
        "entry_cost_total": round(sum(r["cost"] for r in rows if r["is_entry"]), 4),
        "exit_cost_total": round(sum(r["cost"] for r in rows if not r["is_entry"]), 4),
        "list": rows,
    }


def closed(trade_id, pair, tag, profit_pct, hours, rows, exit_engine, side="long", system="system_v4",
           opened="2026-10-05T09:00:00Z", closed_utc="2026-10-05T19:12:00Z", stake=1668.32):
    return {
        "trade_id": trade_id, "pair": pair, "side": side, "tag": tag, "strategy": "NostalgiaForInfinityX8",
        "system_version": system, "leverage": 3.0, "entries": max(1, sum(1 for r in rows if r["is_entry"])),
        "exits": max(1, sum(1 for r in rows if not r["is_entry"])), "opened_utc": opened, "closed_utc": closed_utc,
        "open_rate": 62140.5, "close_rate": 63512.9, "amount": 0.08, "stake": stake, "max_stake": stake * 1.4,
        "fee_open": 0.0005, "fee_close": 0.0005, "funding": -0.14, "mae_pct": -1.8, "mfe_pct": 3.1,
        "hours": hours, "profit_pct": profit_pct, "profit_abs": round(stake * profit_pct / 100.0 * 3, 2),
        "exit": exit_engine, "exit_detail": "exit_long_normal_w_0 ( 200 )", "orders": orders_block(rows),
    }


def open_trade(trade_id, pair, tag, age_hours, unrealized, side="long", opened="2026-10-07T04:00:00Z"):
    rows = [order(f"o{trade_id}1", "entry", "200", "entry", 0.02, 61000.0, opened, opened, cost=1220.0)]
    return {
        "trade_id": trade_id, "pair": pair, "side": side, "tag": tag, "strategy": "NostalgiaForInfinityX8",
        "system_version": "system_v4", "leverage": 3.0, "entries": 1, "exits": 0, "opened_utc": opened,
        "open_rate": 61000.0, "amount": 0.02, "stake": 1220.0, "max_stake": 1220.0, "fee_open": 0.0005,
        "fee_close": None, "funding": 0.0, "mae_pct": -4.2, "mfe_pct": 1.1, "age_hours": age_hours,
        "unrealized_pct": unrealized, "orders": orders_block(rows),
    }


def report(install_id, sent_utc, closed_trades, open_trades, version="18.0.133"):
    profits = [t["profit_pct"] for t in closed_trades]
    return {
        "schema": "nfix8-report/2", "sent_utc": sent_utc, "install_id": install_id,
        "strategy": "NostalgiaForInfinityX8", "strategy_version": version, "exchange": "binance",
        "trading_mode": "futures", "dry_run": False, "window_days": 1,
        "summary": {
            "closed": len(profits), "open": len(open_trades),
            "winrate_pct": round(100.0 * sum(1 for p in profits if p > 0) / len(profits), 1) if profits else None,
            "avg_pct": round(sum(profits) / len(profits), 2) if profits else None,
            "median_pct": None, "best_pct": max(profits) if profits else None, "worst_pct": min(profits) if profits else None,
            "profit_abs": round(sum(t["profit_abs"] for t in closed_trades), 2),
            "avg_hours": None, "avg_entries": None, "grinds": 0, "derisks": 0, "by_tag": {}, "by_exit": {},
        },
        "open_trades": open_trades, "closed_trades": closed_trades,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()

    a1_rows = [
        order("a-1", "entry", "200", "entry", 0.026, 61000.0, "2026-10-05T09:00:00Z", "2026-10-05T09:00:00Z"),
        order("a-2", "grind", "200", "entry", 0.013, 60000.0, "2026-10-05T14:00:00Z", "2026-10-05T14:00:00Z"),
        order("a-3", "derisk", "200", "exit", 0.013, 59800.0, "2026-10-05T15:00:00Z", "2026-10-05T15:00:00Z"),
        order("a-4", "grind", "200", "entry", 0.013, 59200.0, "2026-10-06T02:00:00Z", "2026-10-06T02:00:00Z"),
        order("a-5", "exit", "200", "exit", 0.065, 63512.9, "2026-10-05T19:10:00Z", "2026-10-05T19:12:00Z"),
    ]
    b1_rows = [
        order("b-1", "entry", "700", "entry", 0.02, 66000.0, "2026-10-04T09:00:00Z", "2026-10-04T09:00:00Z"),
        order("b-2", "rebuy", "700", "entry", 0.01, 67200.0, "2026-10-05T01:00:00Z", "2026-10-05T01:00:00Z"),
        order("b-3", "exit", "700", "exit", 0.03, 68400.0, "2026-10-05T20:00:00Z", "2026-10-05T20:00:00Z"),
    ]
    c_rows = [
        order("c-1", "entry", "120", "entry", 0.03, 3000.0, "2026-10-05T10:00:00Z", "2026-10-05T10:00:00Z"),
        order("c-2", "grind", "120", "entry", 0.015, 2950.0, "2026-10-05T18:00:00Z", "2026-10-05T18:00:00Z"),
        order("c-3", "grind", "120", "entry", 0.01, 2900.0, "2026-10-06T06:00:00Z", "2026-10-06T06:00:00Z"),
        order("c-4", "exit", "120", "exit", 0.055, 3150.0, "2026-10-06T12:00:00Z", "2026-10-06T12:00:00Z"),
    ]

    r1 = report(
        "aaa111bbb222", "2026-10-16T09:05:00Z",
        [
            closed(101, "BTC/USDT:USDT", "200", 2.41, 10.2, a1_rows, "long_normal"),
            closed(102, "ETH/USDT:USDT", "700", -3.12, 30.4, b1_rows, "short_normal", side="short",
                   system="system_v3_2", stake=900.0),
        ],
        [open_trade(103, "SOL/USDT:USDT", "200", 42.5, -3.2)],
    )
    r2 = report(
        "ccc333ddd444", "2026-10-16T09:10:00Z",
        [closed(201, "AVAX/USDT:USDT", "120", 4.77, 26.0, c_rows, "long_grind", system="system_v3_2", stake=450.0)],
        [],
    )
    r3 = report(
        "aaa111bbb222", "2026-10-17T09:05:00Z",
        [closed(104, "XRP/USDT:USDT", "200", -2.05, 96.0, a1_rows, "exit_bad_trade_abandon")],
        [open_trade(103, "SOL/USDT:USDT", "200", 66.5, -1.1)],
        version="18.0.134",
    )

    for name, payload in (("report-a1.json", r1), ("report-b1.json", r2), ("report-a2.json", r3)):
        (OUT / name).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    (OUT / "broken.json").write_text('{"install_id": "x", "tra', encoding="utf-8")
    print(f"wrote {len(list(OUT.glob('*.json')))} files to {OUT}")


if __name__ == "__main__":
    main()
