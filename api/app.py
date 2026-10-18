"""Read-only API + dashboard for nfix-contribution v2."""

from __future__ import annotations

import os
import pathlib
from typing import Any, Optional

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DASHBOARD_TOKEN = (os.environ.get("DASHBOARD_TOKEN") or "").strip()
MIN_INSTALLS = max(1, int(os.environ.get("MIN_INSTALLS", "3") or 3))
SCHEMA_PATH = pathlib.Path(os.environ.get("SCHEMA_PATH", "/app/db/schema.sql"))
WEB_DIR = pathlib.Path(os.environ.get("WEB_DIR", "web"))

SORTS = {
    "n": "n DESC",
    "wr": "wr DESC, n DESC",
    "avg": "avg_pct DESC, n DESC",
    "med": "med_pct DESC, n DESC",
    "sum": "sum_pct DESC, n DESC",
    "hours": "med_hours DESC, n DESC",
    "mae": "avg_mae ASC, n DESC",
    "worst": "avg_pct ASC, n DESC",
}

app = FastAPI(title="nfix-contribution", docs_url=None, redoc_url=None, openapi_url=None)


def db() -> psycopg.Connection:
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="database not configured")
    return psycopg.connect(DATABASE_URL, autocommit=True)


def ensure_schema() -> None:
    try:
        with db() as conn:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - startup best effort
        print("schema check failed:", exc)


def requires_token(x_dashboard_token: Optional[str] = Header(default=None),
                   token: Optional[str] = Query(default=None)) -> bool:
    """Detailed trade data stays private: it needs the dashboard token."""
    if not DASHBOARD_TOKEN:
        raise HTTPException(status_code=403, detail="detail endpoints are disabled (DASHBOARD_TOKEN unset)")
    supplied = (x_dashboard_token or token or "").strip()
    if supplied != DASHBOARD_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")
    return True


def public_only(x_dashboard_token: Optional[str] = Header(default=None),
                token: Optional[str] = Query(default=None)) -> bool:
    """True when the caller is anonymous (k-anonymity floor applies)."""
    if not DASHBOARD_TOKEN:
        return True
    return (x_dashboard_token or token or "").strip() != DASHBOARD_TOKEN


def _filters(days: int, version: Optional[str], system_version: Optional[str], side: Optional[str],
             exchange: Optional[str], tag: Optional[str], pair: Optional[str]) -> tuple:
    conds = ["NOT t.is_open", "t.profit_pct IS NOT NULL"]
    params: list = []
    if days and days > 0:
        conds.append("t.closed_utc >= now() - make_interval(days => %s)")
        params.append(days)
    if version:
        conds.append("t.strategy_version = %s")
        params.append(version)
    if system_version:
        conds.append("t.system_version = %s")
        params.append(system_version)
    if side in ("long", "short"):
        conds.append("t.side = %s")
        params.append(side)
    if tag:
        conds.append("t.tag = %s")
        params.append(tag)
    if pair:
        conds.append("t.pair = %s")
        params.append(pair)
    if exchange:
        conds.append("EXISTS (SELECT 1 FROM install i WHERE i.install_id = t.install_id AND i.exchange = %s)")
        params.append(exchange)
    return " AND ".join(conds), params


def _common(days: int = Query(30, ge=0, le=3650), version: Optional[str] = None,
            system_version: Optional[str] = None, side: Optional[str] = None,
            exchange: Optional[str] = None, tag: Optional[str] = None,
            pair: Optional[str] = None) -> dict:
    return {"days": days, "version": version, "system_version": system_version, "side": side,
            "exchange": exchange, "tag": tag, "pair": pair}


@app.on_event("startup")
def _startup() -> None:
    ensure_schema()


@app.get("/healthz")
def healthz() -> dict:
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)


@app.get("/api/meta")
def meta() -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT (SELECT count(*) FROM install),
                   (SELECT count(*) FROM report),
                   (SELECT count(*) FROM trade),
                   (SELECT count(*) FROM trade WHERE is_open),
                   (SELECT count(*) FROM trade WHERE NOT is_open),
                   (SELECT max(sent_utc) FROM report)
            """
        ).fetchone()
        versions = conn.execute(
            "SELECT strategy_version, system_version, count(*) FROM trade GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
        latest_ingest = conn.execute(
            "SELECT ran_utc, source, seen, imported, skipped, failed FROM ingest_log ORDER BY id DESC LIMIT 5"
        ).fetchall()
    return {
        "installs": row[0], "reports": row[1], "trades": row[2], "open": row[3], "closed": row[4],
        "last_report_utc": row[5].isoformat() if row[5] else None,
        "versions": [{"strategy_version": v[0], "system_version": v[1], "n": v[2]} for v in versions],
        "latest_ingest": [
            {"ran_utc": r[0].isoformat(), "source": r[1], "seen": r[2], "imported": r[3],
             "skipped": r[4], "failed": r[5]} for r in latest_ingest
        ],
        "min_installs": MIN_INSTALLS,
        "detail_enabled": bool(DASHBOARD_TOKEN),
    }


def _agg_columns() -> str:
    return """
      count(*) AS n,
      count(*) FILTER (WHERE t.profit_pct > 0) AS wins,
      round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / count(*), 1) AS wr,
      round(avg(t.profit_pct)::numeric, 3) AS avg_pct,
      round(percentile_cont(0.5) WITHIN GROUP (ORDER BY t.profit_pct)::numeric, 3) AS med_pct,
      round(percentile_cont(0.1) WITHIN GROUP (ORDER BY t.profit_pct)::numeric, 3) AS p10,
      round(sum(t.profit_pct)::numeric, 1) AS sum_pct,
      round(avg(t.hours)::numeric, 1) AS avg_hours,
      round(percentile_cont(0.5) WITHIN GROUP (ORDER BY t.hours)::numeric, 1) AS med_hours,
      round(avg(t.mae_pct)::numeric, 2) AS avg_mae,
      round(avg(t.mfe_pct)::numeric, 2) AS avg_mfe,
      round(avg(t.entries)::numeric, 2) AS avg_entries,
      coalesce(sum(t.grinds), 0) AS grinds,
      coalesce(sum(t.derisks), 0) AS derisks,
      count(DISTINCT t.install_id) AS installs,
      round(sum(t.profit_abs)::numeric, 2) AS profit_abs
    """


@app.get("/api/overview")
def overview(f: dict = Depends(_common)) -> dict:
    where, params = _filters(**f)
    with db() as conn:
        totals = conn.execute(
            "SELECT " + _agg_columns() + " FROM trade t WHERE " + where, params
        ).fetchone()
        series = conn.execute(
            """
            SELECT to_char(day, 'YYYY-MM-DD') AS day, n, wins, wr, avg_pct, sum_pct, grinds, derisks
            FROM (
              SELECT t.closed_utc::date AS day,
                     count(*) AS n,
                     count(*) FILTER (WHERE t.profit_pct > 0) AS wins,
                     round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / count(*), 1) AS wr,
                     round(avg(t.profit_pct)::numeric, 3) AS avg_pct,
                     round(sum(t.profit_pct)::numeric, 1) AS sum_pct,
                     coalesce(sum(t.grinds), 0) AS grinds,
                     coalesce(sum(t.derisks), 0) AS derisks
              FROM trade t WHERE """ + where + """
              GROUP BY 1
            ) s ORDER BY day
            """,
            params,
        ).fetchall()
        open_row = conn.execute(
            "SELECT count(*) AS n, round(avg(t.unrealized_pct)::numeric, 3) AS avg_unrealized,"
            " round(avg(t.age_hours)::numeric, 1) AS avg_age_hours FROM trade t"
            " WHERE t.is_open AND (%s::int = 0 OR t.opened_utc >= now() - make_interval(days => %s::int))"
            " AND (%s::text IS NULL OR t.strategy_version = %s::text)"
            " AND (%s::text IS NULL OR t.side = %s::text)",
            (f["days"], f["days"], f["version"], f["version"], f["side"], f["side"]),
        ).fetchone()
    keys = ["n", "wins", "wr", "avg_pct", "med_pct", "p10", "sum_pct", "avg_hours", "med_hours", "avg_mae",
            "avg_mfe", "avg_entries", "grinds", "derisks", "installs", "profit_abs"]
    return {
        "totals": dict(zip(keys, [float(v) if v is not None else None for v in totals])),
        "open": {"n": open_row[0], "avg_unrealized": float(open_row[1]) if open_row[1] is not None else None,
                 "avg_age_hours": float(open_row[2]) if open_row[2] is not None else None},
        "series": [
            {"day": r[0], "n": r[1], "wins": r[2], "wr": float(r[3]), "avg_pct": float(r[4]),
             "sum_pct": float(r[5]), "grinds": r[6], "derisks": r[7]} for r in series
        ],
    }


@app.get("/api/tags")
def tags(f: dict = Depends(_common), sort: str = "n", limit: int = Query(200, ge=1, le=1000),
         minor: bool = Depends(public_only)) -> dict:
    where, params = _filters(**f)
    order = SORTS.get(sort, SORTS["n"])
    having = " HAVING count(DISTINCT t.install_id) >= %s" if minor and MIN_INSTALLS > 1 else ""
    if having:
        params.append(MIN_INSTALLS)
    with db() as conn:
        rows = conn.execute(
            "SELECT t.tag, " + _agg_columns() + " FROM trade t WHERE " + where
            + " GROUP BY t.tag" + having + " ORDER BY " + order + " LIMIT %s",
            params + [limit],
        ).fetchall()
    keys = ["tag", "n", "wins", "wr", "avg_pct", "med_pct", "p10", "sum_pct", "avg_hours", "med_hours",
            "avg_mae", "avg_mfe", "avg_entries", "grinds", "derisks", "installs", "profit_abs"]
    return {"rows": [dict(zip(keys, [r[0]] + [float(v) if v is not None else None for v in r[1:]]))
                     for r in rows],
            "k_anonymity_floor": MIN_INSTALLS if minor else 0}


@app.get("/api/tag/{tag}")
def tag_detail(tag: str, f: dict = Depends(_common)) -> dict:
    kwargs = dict(f)
    kwargs["tag"] = tag
    where, params = _filters(**kwargs)
    with db() as conn:
        pairs = conn.execute(
            "SELECT t.pair, " + _agg_columns() + " FROM trade t WHERE " + where
            + " GROUP BY t.pair ORDER BY n DESC LIMIT 25",
            params,
        ).fetchall()
        exits = conn.execute(
            "SELECT coalesce(nullif(regexp_replace(coalesce(t.exit, '?'), '\\( *[0-9 ]+\\)$', ''), ''), '?') AS exit,"
            " count(*) AS n, round(avg(t.profit_pct)::numeric, 3) AS avg_pct,"
            " round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / count(*), 1) AS wr"
            " FROM trade t WHERE " + where + " GROUP BY 1 ORDER BY n DESC LIMIT 20",
            params,
        ).fetchall()
        weekly = conn.execute(
            "SELECT to_char(date_trunc('week', t.closed_utc), 'YYYY-MM-DD') AS week, count(*) AS n,"
            " round(avg(t.profit_pct)::numeric, 3) AS avg_pct,"
            " round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / count(*), 1) AS wr"
            " FROM trade t WHERE " + where + " GROUP BY 1 ORDER BY 1 DESC LIMIT 30",
            params,
        ).fetchall()
        orders = conn.execute(
            """
            SELECT o.kind, count(*) AS n, round(avg(o.price)::numeric, 6) AS avg_price,
                   coalesce(sum(o.filled), 0) AS filled
            FROM trade_order o
            JOIN trade t ON t.install_id = o.install_id AND t.trade_id = o.trade_id
            WHERE """ + where + """ AND NOT t.is_open AND o.kind IS NOT NULL
            GROUP BY o.kind ORDER BY n DESC
            """,
            params,
        ).fetchall()
    pair_keys = ["pair", "n", "wins", "wr", "avg_pct", "med_pct", "p10", "sum_pct", "avg_hours", "med_hours",
                 "avg_mae", "avg_mfe", "avg_entries", "grinds", "derisks", "installs", "profit_abs"]
    return {
        "tag": tag,
        "by_pair": [dict(zip(pair_keys, [r[0]] + [float(v) if v is not None else None for v in r[1:]]))
                    for r in pairs],
        "by_exit": [{"exit": r[0], "n": r[1], "avg_pct": float(r[2]), "wr": float(r[3])} for r in exits],
        "weekly": [{"week": r[0], "n": r[1], "avg_pct": float(r[2]), "wr": float(r[3])} for r in weekly],
        "orders": [{"kind": r[0], "n": r[1], "avg_price": float(r[2]) if r[2] is not None else None,
                    "filled": float(r[3])} for r in orders],
    }


@app.get("/api/grind")
def grind(f: dict = Depends(_common), minor: bool = Depends(public_only)) -> dict:
    where, params = _filters(**f)
    with db() as conn:
        by_group = conn.execute(
            """
            SELECT CASE WHEN t.grinds > 0 AND t.derisks > 0 THEN 'grind+derisk'
                        WHEN t.grinds > 0 THEN 'grind only'
                        WHEN t.derisks > 0 THEN 'derisk only'
                        ELSE 'plain' END AS bucket,
                   count(*) AS n,
                   round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / count(*), 1) AS wr,
                   round(avg(t.profit_pct)::numeric, 3) AS avg_pct,
                   round(percentile_cont(0.1) WITHIN GROUP (ORDER BY t.profit_pct)::numeric, 3) AS p10,
                   round(avg(t.hours)::numeric, 1) AS avg_hours,
                   round(avg(t.mae_pct)::numeric, 2) AS avg_mae,
                   round(avg(t.mfe_pct)::numeric, 2) AS avg_mfe,
                   round(avg(t.entries)::numeric, 2) AS avg_entries,
                   round(avg(t.max_stake / nullif(t.stake, 0))::numeric, 2) AS avg_stake_growth
            FROM trade t WHERE """ + where + """
            GROUP BY 1 ORDER BY n DESC
            """,
            params,
        ).fetchall()
        kinds = conn.execute(
            """
            SELECT o.kind, count(*) AS n, count(DISTINCT (o.install_id, o.trade_id)) AS trades,
                   round(sum(o.filled)::numeric, 4) AS filled
            FROM trade_order o
            JOIN trade t ON t.install_id = o.install_id AND t.trade_id = o.trade_id
            WHERE """ + where + """ AND o.kind IS NOT NULL
            GROUP BY o.kind ORDER BY n DESC
            """,
            params,
        ).fetchall()
        tags = conn.execute(
            """
            SELECT t.tag, count(*) AS n, coalesce(sum(t.grinds), 0) AS grinds,
                   coalesce(sum(t.derisks), 0) AS derisks,
                   round(avg(t.entries)::numeric, 2) AS avg_entries,
                   round(avg(t.profit_pct)::numeric, 3) AS avg_pct,
                   round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / count(*), 1) AS wr,
                   round(avg(t.max_stake / nullif(t.stake, 0))::numeric, 2) AS avg_stake_growth
            FROM trade t WHERE """ + where + """
            GROUP BY t.tag HAVING coalesce(sum(t.grinds), 0) + coalesce(sum(t.derisks), 0) > 0
            ORDER BY (coalesce(sum(t.grinds), 0) + coalesce(sum(t.derisks), 0)) DESC LIMIT 40
            """,
            params,
        ).fetchall()
        worst = conn.execute(
            """
            SELECT date_trunc('week', t.closed_utc)::date AS week, count(*) AS n,
                   round(avg(t.profit_pct)::numeric, 3) AS avg_pct
            FROM trade t WHERE """ + where + """ AND t.grinds > 0 GROUP BY 1 ORDER BY 1 DESC LIMIT 26
            """,
            params,
        ).fetchall()
    return {
        "by_group": [{"bucket": r[0], "n": r[1], "wr": float(r[2]), "avg_pct": float(r[3]),
                      "p10": float(r[4]), "avg_hours": float(r[5]), "avg_mae": float(r[6]),
                      "avg_mfe": float(r[7]), "avg_entries": float(r[8]),
                      "avg_stake_growth": float(r[9]) if r[9] is not None else None} for r in by_group],
        "kinds": [{"kind": r[0], "n": r[1], "trades": r[2], "filled": float(r[3] or 0)} for r in kinds],
        "by_tag": [{"tag": r[0], "n": r[1], "grinds": r[2], "derisks": r[3], "avg_entries": float(r[4]),
                    "avg_pct": float(r[5]), "wr": float(r[6]),
                    "avg_stake_growth": float(r[7]) if r[7] is not None else None} for r in tags],
        "weekly_grind": [{"week": r[0].isoformat(), "n": r[1], "avg_pct": float(r[2])} for r in worst],
    }


@app.get("/api/versions")
def versions(f: dict = Depends(_common)) -> dict:
    where, params = _filters(**f)
    with db() as conn:
        rows = conn.execute(
            "SELECT t.strategy_version, t.system_version, " + _agg_columns() + " FROM trade t WHERE "
            + where + " GROUP BY 1, 2 ORDER BY n DESC",
            params,
        ).fetchall()
        installs = conn.execute(
            """
            SELECT i.install_id, i.exchange, i.trading_mode, i.strategy_version, i.reports,
                   i.first_seen_utc, i.last_seen_utc,
                   (SELECT count(*) FROM trade t WHERE t.install_id = i.install_id) AS trades,
                   (SELECT count(*) FROM trade t WHERE t.install_id = i.install_id AND NOT t.is_open) AS closed,
                   (SELECT round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / nullif(count(*), 0), 1)
                      FROM trade t WHERE t.install_id = i.install_id AND NOT t.is_open) AS wr,
                   (SELECT round(avg(t.profit_pct)::numeric, 3) FROM trade t
                      WHERE t.install_id = i.install_id AND NOT t.is_open) AS avg_pct
            FROM install i ORDER BY i.last_seen_utc DESC
            """
        ).fetchall()
    keys = ["n", "wins", "wr", "avg_pct", "med_pct", "p10", "sum_pct", "avg_hours", "med_hours", "avg_mae",
            "avg_mfe", "avg_entries", "grinds", "derisks", "installs", "profit_abs"]
    return {
        "rows": [dict({"strategy_version": r[0], "system_version": r[1]},
                      **dict(zip(keys, [float(v) if v is not None else None for v in r[2:]]))) for r in rows],
        "installs": [
            {"install_id": r[0], "masked": r[0][:4] + "…" + r[0][-2:], "exchange": r[1], "trading_mode": r[2],
             "strategy_version": r[3], "reports": r[4], "first_seen_utc": r[5].isoformat(),
             "last_seen_utc": r[6].isoformat(), "trades": r[7], "closed": r[8],
             "wr": float(r[9]) if r[9] is not None else None,
             "avg_pct": float(r[10]) if r[10] is not None else None} for r in installs
        ],
    }


@app.get("/api/pairs")
def pairs(f: dict = Depends(_common), minor: bool = Depends(public_only)) -> dict:
    where, params = _filters(**f)
    having = " HAVING count(DISTINCT t.install_id) >= %s" if minor and MIN_INSTALLS > 1 else ""
    if having:
        params.append(MIN_INSTALLS)
    with db() as conn:
        rows = conn.execute(
            "SELECT t.pair, " + _agg_columns() + " FROM trade t WHERE " + where
            + " GROUP BY t.pair" + having + " ORDER BY n DESC LIMIT 200",
            params,
        ).fetchall()
        sides = conn.execute(
            "SELECT t.side, " + _agg_columns() + " FROM trade t WHERE " + where
            + " GROUP BY t.side ORDER BY n DESC",
            params[: len(params) - (1 if having else 0)],
        ).fetchall()
    keys = ["pair", "n", "wins", "wr", "avg_pct", "med_pct", "p10", "sum_pct", "avg_hours", "med_hours",
            "avg_mae", "avg_mfe", "avg_entries", "grinds", "derisks", "installs", "profit_abs"]
    side_keys = ["side", "n", "wins", "wr", "avg_pct", "med_pct", "p10", "sum_pct", "avg_hours", "med_hours",
                 "avg_mae", "avg_mfe", "avg_entries", "grinds", "derisks", "installs", "profit_abs"]
    return {
        "rows": [dict(zip(keys, [r[0]] + [float(v) if v is not None else None for v in r[1:]])) for r in rows],
        "sides": [dict(zip(side_keys, [r[0]] + [float(v) if v is not None else None for v in r[1:]]))
                  for r in sides],
    }


@app.get("/api/exits")
def exits(f: dict = Depends(_common)) -> dict:
    where, params = _filters(**f)
    with db() as conn:
        rows = conn.execute(
            "SELECT coalesce(nullif(regexp_replace(coalesce(t.exit, '?'), '\\( *[0-9 ]+\\)$', ''), ''), '?') AS exit,"
            " count(*) AS n, round(100.0 * count(*) FILTER (WHERE t.profit_pct > 0) / count(*), 1) AS wr,"
            " round(avg(t.profit_pct)::numeric, 3) AS avg_pct,"
            " round(sum(t.profit_pct)::numeric, 1) AS sum_pct,"
            " round(avg(t.hours)::numeric, 1) AS avg_hours,"
            " round(avg(t.mae_pct)::numeric, 2) AS avg_mae"
            " FROM trade t WHERE " + where + " GROUP BY 1 ORDER BY n DESC LIMIT 60",
            params,
        ).fetchall()
    return {"rows": [{"exit": r[0], "n": r[1], "wr": float(r[2]), "avg_pct": float(r[3]),
                      "sum_pct": float(r[4]), "avg_hours": float(r[5]), "avg_mae": float(r[6])} for r in rows]}


@app.get("/api/worst")
def worst(f: dict = Depends(_common), n: int = Query(25, ge=1, le=200),
          _: bool = Depends(requires_token)) -> dict:
    where, params = _filters(**f)
    with db() as conn:
        rows = conn.execute(
            "SELECT t.install_id, t.trade_id, t.pair, t.side, t.tag, t.opened_utc, t.closed_utc, t.hours,"
            " t.profit_pct, t.profit_abs, t.mae_pct, t.mfe_pct, t.entries, t.grinds, t.derisks, t.stake,"
            " t.max_stake, t.exit, t.exit_detail, t.system_version, t.strategy_version"
            " FROM trade t WHERE " + where + " ORDER BY t.profit_pct ASC LIMIT %s",
            params + [n],
        ).fetchall()
    return {"rows": [_trade_row(r) for r in rows]}


def _trade_row(r: tuple) -> dict:
    return {
        "install_id": r[0], "install": r[0][:4] + "…" + r[0][-2:], "trade_id": r[1], "pair": r[2], "side": r[3],
        "tag": r[4], "opened_utc": r[5].isoformat() if r[5] else None,
        "closed_utc": r[6].isoformat() if r[6] else None, "hours": _num(r[7]), "profit_pct": _num(r[8]),
        "profit_abs": _num(r[9]), "mae_pct": _num(r[10]), "mfe_pct": _num(r[11]), "entries": r[12],
        "grinds": r[13], "derisks": r[14], "stake": _num(r[15]), "max_stake": _num(r[16]),
        "exit": r[17], "exit_detail": r[18], "system_version": r[19], "strategy_version": r[20],
    }


def _num(value: Any) -> Optional[float]:
    return None if value is None else float(value)


@app.get("/api/trades")
def trades(f: dict = Depends(_common), page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=500),
           _: bool = Depends(requires_token)) -> dict:
    where, params = _filters(**f)
    offset = (page - 1) * per_page
    with db() as conn:
        total = conn.execute("SELECT count(*) FROM trade t WHERE " + where, params).fetchone()[0]
        rows = conn.execute(
            "SELECT t.install_id, t.trade_id, t.pair, t.side, t.tag, t.opened_utc, t.closed_utc, t.hours,"
            " t.profit_pct, t.profit_abs, t.mae_pct, t.mfe_pct, t.entries, t.grinds, t.derisks, t.stake,"
            " t.max_stake, t.exit, t.exit_detail, t.system_version, t.strategy_version"
            " FROM trade t WHERE " + where + " ORDER BY t.closed_utc DESC LIMIT %s OFFSET %s",
            params + [per_page, offset],
        ).fetchall()
    return {"total": total, "page": page, "per_page": per_page, "rows": [_trade_row(r) for r in rows]}


@app.get("/api/trade/{install_id}/{trade_id}")
def trade_detail(install_id: str, trade_id: int, _: bool = Depends(requires_token)) -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT t.install_id, t.trade_id, t.pair, t.side, t.tag, t.opened_utc, t.closed_utc, t.hours,"
            " t.profit_pct, t.profit_abs, t.mae_pct, t.mfe_pct, t.entries, t.grinds, t.derisks, t.stake,"
            " t.max_stake, t.exit, t.exit_detail, t.system_version, t.strategy_version"
            " FROM trade t WHERE t.install_id = %s AND t.trade_id = %s",
            (install_id, trade_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="trade not found")
        orders = conn.execute(
            "SELECT order_id, kind, tag, status, amount, filled, price, cost, placed_utc, filled_utc"
            " FROM trade_order WHERE install_id = %s AND trade_id = %s ORDER BY placed_utc NULLS LAST, order_id",
            (install_id, trade_id),
        ).fetchall()
    detail = _trade_row(row)
    detail["orders"] = [
        {"order_id": o[0], "kind": o[1], "tag": o[2], "status": o[3], "amount": _num(o[4]),
         "filled": _num(o[5]), "price": _num(o[6]), "cost": _num(o[7]),
         "placed_utc": o[8].isoformat() if o[8] else None, "filled_utc": o[9].isoformat() if o[9] else None}
        for o in orders
    ]
    return detail


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
