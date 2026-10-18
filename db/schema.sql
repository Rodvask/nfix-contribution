-- nfix-contribution v2 - schema (idempotent, applied at API and ingest startup)
-- Per-installation anonymous telemetry: one report per install per day, carrying the trades
-- (and their orders) of the configured window.

CREATE TABLE IF NOT EXISTS install (
  install_id       text PRIMARY KEY,
  first_seen_utc   timestamptz NOT NULL DEFAULT now(),
  last_seen_utc    timestamptz NOT NULL DEFAULT now(),
  reports          integer NOT NULL DEFAULT 0,
  strategy         text,
  strategy_version text,
  exchange         text,
  trading_mode     text
);

CREATE TABLE IF NOT EXISTS report (
  report_uid       bigserial PRIMARY KEY,
  install_id       text NOT NULL REFERENCES install(install_id) ON DELETE CASCADE,
  sent_utc         timestamptz NOT NULL,
  sent_day         date NOT NULL,
  schema           text,
  strategy         text,
  strategy_version text,
  exchange         text,
  trading_mode     text,
  dry_run          boolean,
  window_days      integer,
  summary          jsonb NOT NULL DEFAULT '{}'::jsonb,
  raw_path         text,
  received_utc     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (install_id, sent_day)
);

CREATE TABLE IF NOT EXISTS trade (
  install_id       text NOT NULL REFERENCES install(install_id) ON DELETE CASCADE,
  trade_id         bigint NOT NULL,
  pair             text NOT NULL,
  side             text,
  tag              text,
  strategy         text,
  strategy_version text,
  system_version   text,
  leverage         numeric,
  entries          integer,
  exits            integer,
  is_open          boolean NOT NULL DEFAULT false,
  opened_utc       timestamptz NOT NULL,
  closed_utc       timestamptz,
  open_rate        numeric,
  close_rate       numeric,
  amount           numeric,
  stake            numeric,
  max_stake        numeric,
  fee_open         numeric,
  fee_close        numeric,
  funding          numeric,
  mae_pct          numeric,
  mfe_pct          numeric,
  hours            numeric,
  profit_pct       numeric,
  profit_abs       numeric,
  exit             text,
  exit_detail      text,
  age_hours        numeric,
  unrealized_pct   numeric,
  grinds           integer NOT NULL DEFAULT 0,
  derisks          integer NOT NULL DEFAULT 0,
  last_report_utc  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (install_id, trade_id)
);

CREATE TABLE IF NOT EXISTS trade_order (
  install_id  text NOT NULL,
  trade_id    bigint NOT NULL,
  order_id    text NOT NULL,
  kind        text,
  tag         text,
  status      text,
  amount      numeric,
  filled      numeric,
  price       numeric,
  cost        numeric,
  fee_base    numeric,
  funding_fee numeric,
  placed_utc  timestamptz,
  filled_utc  timestamptz,
  PRIMARY KEY (install_id, trade_id, order_id),
  FOREIGN KEY (install_id, trade_id) REFERENCES trade(install_id, trade_id) ON DELETE CASCADE
);

-- Ingestion bookkeeping
CREATE TABLE IF NOT EXISTS ingest_seen (
  source        text NOT NULL,
  message_id    text NOT NULL,
  attachment_id text NOT NULL DEFAULT '',
  seen_utc      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source, message_id, attachment_id)
);

CREATE TABLE IF NOT EXISTS ingest_state (
  scope     text PRIMARY KEY,
  value     text,
  updated_utc timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_log (
  id        bigserial PRIMARY KEY,
  ran_utc   timestamptz NOT NULL DEFAULT now(),
  source    text,
  seen      integer NOT NULL DEFAULT 0,
  imported  integer NOT NULL DEFAULT 0,
  skipped   integer NOT NULL DEFAULT 0,
  failed    integer NOT NULL DEFAULT 0,
  note      text
);

CREATE INDEX IF NOT EXISTS trade_tag_idx ON trade (tag);
CREATE INDEX IF NOT EXISTS trade_pair_idx ON trade (pair);
CREATE INDEX IF NOT EXISTS trade_opened_idx ON trade (opened_utc DESC);
CREATE INDEX IF NOT EXISTS trade_closed_idx ON trade (closed_utc DESC);
CREATE INDEX IF NOT EXISTS trade_open_idx ON trade (is_open);
CREATE INDEX IF NOT EXISTS trade_exit_idx ON trade (exit);
CREATE INDEX IF NOT EXISTS trade_version_idx ON trade (strategy_version, system_version);
CREATE INDEX IF NOT EXISTS trade_order_kind_idx ON trade_order (kind);
