"""Unit tests for the ingestion helpers (no database needed)."""
import importlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ingest = importlib.import_module("ingest.discord_ingest")


def _trade(**over):
    base = {
        "trade_id": 7, "pair": "BTC/USDT:USDT", "side": "long", "tag": "200", "strategy": "NFIX8",
        "strategy_version": "18.0.133", "system_version": "system_v4", "leverage": 3.0, "entries": 2, "exits": 1,
        "opened_utc": "2026-10-05T09:00:00Z", "open_rate": 61000.0, "amount": 0.02, "stake": 1220.0,
        "max_stake": 1700.0, "fee_open": 0.0005, "fee_close": 0.0005, "funding": 0.0, "mae_pct": -1.5,
        "mfe_pct": 2.5, "hours": 10.0, "profit_pct": 2.41, "profit_abs": 88.0, "exit": "long_normal",
        "exit_detail": "exit_long_normal_w_0 ( 200 )",
        "orders": {"grinds": 1, "derisks": 0, "counts_by_kind": {"entry": 2, "grind": 1, "exit": 1},
                   "list": [{"order_id": "o1", "kind": "entry", "amount": 0.02, "filled": 0.02},
                            {"order_id": "o2", "kind": "grind", "amount": 0.01, "filled": 0.01}]},
    }
    base.update(over)
    return base


def test_trade_values_keeps_the_allowlist_and_counts_orders():
    values = ingest.trade_values("abc123", _trade(), False)
    row = dict(zip(ingest.TRADE_COLUMNS, values))
    assert row["install_id"] == "abc123"
    assert row["trade_id"] == 7
    assert row["tag"] == "200"
    assert row["is_open"] is False
    assert row["grinds"] == 1 and row["derisks"] == 0
    assert row["profit_pct"] == 2.41
    assert row["exit_detail"] == "exit_long_normal_w_0 ( 200 )"


def test_grind_counts_fall_back_to_counts_by_kind():
    trade = _trade(orders={"counts_by_kind": {"grind": 3, "derisk": 2}, "list": []})
    assert ingest._grind_counts(trade) == (3, 2)


def test_order_key_prefers_order_id_and_is_stable_without_it():
    assert ingest.order_key({"order_id": "x9"}, 0) == "x9"
    a = ingest.order_key({"kind": "grind", "tag": "200", "placed_utc": "2026-10-05T09:00:00Z", "amount": 1.0}, 3)
    b = ingest.order_key({"kind": "grind", "tag": "200", "placed_utc": "2026-10-05T09:00:00Z", "amount": 1.0}, 3)
    assert a == b and a != ingest.order_key({"kind": "grind"}, 4)


@pytest.mark.parametrize(
    "payload,message",
    [
        ({}, "unsupported schema"),
        ({"schema": "nfix8-report/2"}, "missing install_id"),
        ({"schema": "nfix8-report/2", "install_id": "a"}, "missing sent_utc"),
        ({"schema": "nfix9-report/1", "install_id": "a", "sent_utc": "2026-10-16T09:00:00Z"}, "unsupported schema"),
    ],
)
def test_import_rejects_invalid_payloads(payload, message):
    with pytest.raises(ValueError) as excinfo:
        ingest.import_payload(None, payload)
    assert message in str(excinfo.value)


def test_fixture_matches_the_documented_schema():
    fixture_dir = ROOT / "tests" / "fixtures"
    assert (fixture_dir / "make_fixture.py").is_file()
    report_path = ROOT / "data" / "fixtures" / "report-a1.json"
    if not report_path.is_file():
        pytest.skip("fixtures not generated (run tests/fixtures/make_fixture.py)")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "nfix8-report/2"
    for key in ("install_id", "sent_utc", "summary", "closed_trades", "open_trades"):
        assert key in payload
    for trade in payload["closed_trades"] + payload["open_trades"]:
        assert "orders" in trade and "list" in trade["orders"]
