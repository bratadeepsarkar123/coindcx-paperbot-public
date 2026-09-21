# CoinDCX Phase-1 paper trader (Bratadeep)

Unattended **paper** trading bot. It reads **live CoinDCX public market data** (India-accessible spot), sizes hypothetical positions with a capped Kelly rule, and writes fills to a local SQLite ledger.

It **never places real orders**. There is no CoinDCX API key in the default path. A live-broker stub exists only to fail closed.

This is not Polymarket, not a multi-user platform, and not a web app. One CLI on a box (laptop or Azure Linux Standard_B2s).

## What it does each loop (~2 minutes by default)

1. Pulls `GET /exchange/ticker` and 1-minute candles for a whitelist (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT` by default).
2. Evaluates a **short-horizon momentum + volume** signal on closed candles (see `docs/strategy.md`).
3. Sizes with Kelly (half-Kelly default), **hard-capped at 6% of current paper equity**.
4. Records paper fills with CoinDCX-ish taker fees (20 bps + 18% GST on the fee, configurable).
5. Marks to market in INR (USDT pairs converted via `USDTINR`).
6. Honors a kill file, a daily max-loss circuit breaker (Asia/Kolkata), and `MAX_OPEN_POSITIONS`.

## Quick start

Python 3.11+. No third-party runtime deps.

```bash
cd /path/to/this/repo
python3 -m venv .venv
source .venv/bin/activate
cp .env.example .env          # optional; defaults are already paper-safe
python3 -m pip install -e ".[dev]"   # or skip; stdlib is enough to run

# sanity-check public CoinDCX (no keys)
python3 -m paperbot doctor

# one live scan into the virtual ledger
python3 -m paperbot run --once

# unattended loop (Ctrl-C to stop; ledger is restart-safe)
python3 -m paperbot run

# what happened?
python3 -m paperbot status
python3 -m paperbot pnl
```

If CoinDCX public HTTP is down, replay a deterministic fixture (still paper):

```bash
python3 -m paperbot run --fixture --loops 12 --interval 1
python3 -m paperbot status
```

## CLI

| Command | Purpose |
| --- | --- |
| `python -m paperbot run` | Loop forever on `SCAN_INTERVAL_SEC` |
| `python -m paperbot run --once` | Single scan |
| `python -m paperbot run --loops N` | N scans then exit |
| `python -m paperbot run --fixture` | Offline candles |
| `python -m paperbot status` | Equity, positions, last fills |
| `python -m paperbot pnl` | Closed-trade table |
| `python -m paperbot kill` | Write `data/KILL` — next loop flattens and blocks entries |
| `python -m paperbot unkilled` | Remove kill file |
| `python -m paperbot doctor` | Print live tickers + remind you this is paper-only |

## Config

All knobs are env / `.env` (see `.env.example`). Important ones:

| Variable | Default | Meaning |
| --- | --- |
| `PAPER_BANKROLL_INR` | `100000` | Starting virtual INR |
| `SCAN_INTERVAL_SEC` | `120` | Loop period (1–5 min is the design range) |
| `PAIRS` | `BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT` | CoinDCX `market` names |
| `KELLY_CAP` | `0.06` | Max fraction of equity; code also clamps to 6% |
| `HALF_KELLY` | `true` | Use half-Kelly |
| `MAX_DAILY_LOSS_PCT` | `0.03` | Flatten + halt new entries for the IST day |
| `MAX_OPEN_POSITIONS` | `2` | Concurrent paper positions |
| `FEE_BPS` | `20` | Taker fee (CoinDCX-ish base spot) |
| `FEE_GST_PCT` | `18` | GST on the fee |
| `DATA_SOURCE` | `live` | `live` or `fixture` |
| `BROKER` | `paper` | Anything else refuses to start |

Strategy parameters (`MOM_*`) are documented in `docs/strategy.md`.

## Safety (read this)

- Default broker is paper. `assert_paper_only()` refuses to start if `ARM_LIVE_TRADING`, `LIVE_CONFIRM`, or CoinDCX keys are set.
- `LiveBroker` **cannot be constructed** and never calls `/exchange/v1/orders/*`.
- Kill switch: `python -m paperbot kill` or `touch data/KILL`.
- Daily breaker uses **IST** midnight, not UTC.

## Tests

```bash
python3 -m pip install pytest
python3 -m pytest
```

Coverage: Kelly math, fee application, ledger restart/idempotency, MTM, kill/breaker, live-path refuse, fixture loop fills.

## Azure Linux / Docker

- VM notes, rough B2s cost, and **budget alerts**: `docs/azure-b2s.md`
- systemd unit: `deploy/paperbot.service`
- Compose (from repo root): `docker compose -f deploy/docker-compose.yml up --build -d`

## Layout

```
paperbot/          # client, strategy, Kelly, paper broker, loop, CLI
tests/
docs/strategy.md
docs/azure-b2s.md
docs/coindcx-api.md
fixtures/          # live snapshot + generated synthetic momentum
deploy/
```

Owner: **Bratadeep**. Private personal project. Paper only until an edge is proven in the ledger.
