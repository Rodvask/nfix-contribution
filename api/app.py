"""nfix-contribution receiver: anonymous aggregate trade telemetry.

Collects ONLY pre-aggregated buckets (one row per install/week/tag).
Trade-level fields are rejected by the schema. No client IPs are read,
logged, or stored anywhere in this service.
"""
import os
from datetime import date, datetime, timedelta

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATABASE_URL = os.environ["DATABASE_URL"]
MIN_INSTALLS = int(os.environ.get("MIN_INSTALLS", "3"))
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "90"))

DDL = """
CREATE TABLE IF NOT EXISTS pulses (
  install_id TEXT NOT NULL,
  week DATE NOT NULL,
  strategy_version TEXT NOT NULL,
  exchange TEXT NOT NULL,
  market TEXT NOT NULL,
  dry_run BOOLEAN NOT NULL,
  tag TEXT NOT NULL,
  direction TEXT NOT NULL,
  fires INT NOT NULL CHECK (fires > 0 AND fires < 100000),
  wins INT NOT NULL CHECK (wins >= 0),
  avg_profit_pct DOUBLE PRECISION NOT NULL CHECK (avg_profit_pct > -100 AND avg_profit_pct < 10000),
  avg_duration_min DOUBLE PRECISION NOT NULL CHECK (avg_duration_min >= 0 AND avg_duration_min < 525600),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT wins_le_fires CHECK (wins <= fires),
  PRIMARY KEY (install_id, week, strategy_version, exchange, market, dry_run, tag, direction)
);
"""

app = FastAPI(title="nfix-contribution")

DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
  install_id TEXT NOT NULL,
  hour TIMESTAMPTZ NOT NULL,
  strategy_version TEXT NOT NULL,
  exchange TEXT NOT NULL,
  market TEXT NOT NULL,
  dry_run BOOLEAN NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('open','close')),
  tag TEXT NOT NULL,
  pair TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('long','short')),
  profit_pct DOUBLE PRECISION,
  duration_min DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_hour_idx ON events (hour);
"""


def db():
    return psycopg.connect(DATABASE_URL)


class TagBucket(BaseModel):
    tag: str = Field(max_length=32)
    direction: str = Field(pattern="^(long|short)$")
    fires: int = Field(gt=0, lt=100000)
    wins: int = Field(ge=0)
    avg_profit_pct: float = Field(gt=-100, lt=10000)
    avg_duration_min: float = Field(ge=0, lt=525600)


class PulseIn(BaseModel):
    # Strict schema: any trade-level field (prices, stakes, balances)
    # is rejected instead of ignored, so senders fail loudly.
    install_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    week: date
    strategy_version: str = Field(max_length=64)
    exchange: str = Field(max_length=32)
    market: str = Field(max_length=16)
    dry_run: bool
    tags: list[TagBucket] = Field(min_length=1, max_length=500)

    model_config = {"extra": "forbid"}


@app.on_event("startup")
def init():
    with db() as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute(DDL_EVENTS)


@app.get("/health")
def health():
    return {"ok": True}


class LiveEvent(BaseModel):
    # Real-time count events. No prices, stakes, balances, or exact
    # timestamps: `hour` is a UTC hour bucket, never the fill time.
    install_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    hour: datetime
    strategy_version: str = Field(max_length=64)
    exchange: str = Field(max_length=32)
    market: str = Field(max_length=16)
    dry_run: bool
    kind: str = Field(pattern="^(open|close)$")
    tag: str = Field(max_length=32)
    pair: str = Field(max_length=32)
    side: str = Field(pattern="^(long|short)$")
    profit_pct: float | None = Field(default=None, gt=-100, lt=10000)
    duration_min: float | None = Field(default=None, ge=0, lt=525600)

    model_config = {"extra": "forbid"}


@app.post("/v1/event", status_code=202)
def ingest_event(e: LiveEvent):
    with db() as conn, conn.cursor() as cur:
        # Real-time data must not accumulate: keep 48h max.
        cur.execute("DELETE FROM events WHERE created_at < now() - interval '48 hours'")
        cur.execute(
            """INSERT INTO events
               (install_id, hour, strategy_version, exchange, market, dry_run,
                kind, tag, pair, side, profit_pct, duration_min)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (e.install_id, e.hour, e.strategy_version, e.exchange, e.market,
             e.dry_run, e.kind, e.tag, e.pair, e.side,
             e.profit_pct, e.duration_min),
        )
    return {"accepted": 1}


@app.get("/v1/pulse")
def pulse(strategy_version: str, hours: int = 24):
    """Crowd counts per tag x pair over the last `hours` (max 48).
    Pairs with fewer than MIN_INSTALLS distinct installs are suppressed."""
    hours = max(1, min(hours, 48))
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT tag, pair, side,
                      SUM(CASE WHEN kind='open' THEN 1 ELSE 0 END) AS opens,
                      SUM(CASE WHEN kind='close' THEN 1 ELSE 0 END) AS closes,
                      AVG(profit_pct) FILTER (WHERE kind='close') AS avg_close_pct,
                      COUNT(DISTINCT install_id) AS installs
               FROM events
               WHERE strategy_version = %s
                 AND created_at >= now() - make_interval(hours => %s)
               GROUP BY tag, pair, side""",
            (strategy_version, hours),
        )
        rows = cur.fetchall()
    out = [{"tag": t, "pair": p, "side": s, "opens": o, "closes": c,
             "avg_close_pct": round(a, 2) if a is not None else None}
           for t, p, s, o, c, a, n in rows if n >= MIN_INSTALLS]
    return {"rows": sorted(out, key=lambda r: (-r["opens"], r["pair"]))}
@app.post("/v1/pulse", status_code=202)
def ingest(p: PulseIn):
    if any(t.wins > t.fires for t in p.tags):
        raise HTTPException(422, "wins must not exceed fires")
    with db() as conn, conn.cursor() as cur:
        # Retention: raw rows older than RETENTION_DAYS are dropped on write.
        cur.execute("DELETE FROM pulses WHERE created_at < now() - make_interval(days => %s)",
                    (RETENTION_DAYS,))
        for t in p.tags:
            cur.execute(
                """INSERT INTO pulses
                   (install_id, week, strategy_version, exchange, market, dry_run,
                    tag, direction, fires, wins, avg_profit_pct, avg_duration_min)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (p.install_id, p.week, p.strategy_version, p.exchange, p.market,
                 p.dry_run, t.tag, t.direction, t.fires, t.wins,
                 t.avg_profit_pct, t.avg_duration_min),
            )
    return {"accepted": len(p.tags)}


@app.get("/v1/leaderboard")
def leaderboard(strategy_version: str, exchange: str = "", weeks: int = 12):
    """Win rate per tag x exchange. Groups with fewer than MIN_INSTALLS
    distinct installs are suppressed (k-anonymity)."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT tag, exchange, market, dry_run,
                      SUM(fires) AS fires, SUM(wins) AS wins,
                      AVG(avg_profit_pct) AS avg_profit_pct,
                      AVG(avg_duration_min) AS avg_duration_min,
                      COUNT(DISTINCT install_id) AS installs
               FROM pulses
               WHERE strategy_version = %s
                 AND (%s = '' OR exchange = %s)
                 AND week >= CURRENT_DATE - make_interval(weeks => %s)
               GROUP BY tag, exchange, market, dry_run""",
            (strategy_version, exchange, exchange, weeks),
        )
        rows = cur.fetchall()
    out = []
    for tag, exc, market, dry_run, fires, wins, avg_p, avg_d, installs in rows:
        if installs < MIN_INSTALLS:
            continue
        out.append({
            "tag": tag, "exchange": exc, "market": market, "dry_run": dry_run,
            "fires": fires, "wins": wins,
            "win_rate": round(wins / fires, 4) if fires else 0,
            "avg_profit_pct": round(avg_p, 2),
            "avg_duration_min": round(avg_d, 1),
            "installs": installs,
        })
    return {"rows": sorted(out, key=lambda r: (r["fires"], r["tag"]), reverse=True)}


# Dashboard (static). Mounted last so /v1/* and /health keep priority.
app.mount("/", StaticFiles(directory="web", html=True), name="web")
