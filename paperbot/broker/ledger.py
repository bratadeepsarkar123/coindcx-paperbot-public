"""SQLite paper ledger. Restart-safe. Money stored as decimal strings."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from paperbot.sizer.kelly import TradeSample

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    market TEXT NOT NULL,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT NOT NULL,
    qty TEXT NOT NULL,
    price TEXT NOT NULL,
    quote_ccy TEXT NOT NULL,
    notional_quote TEXT NOT NULL,
    notional_inr TEXT NOT NULL,
    fee_quote TEXT NOT NULL,
    fee_inr TEXT NOT NULL,
    usdt_inr TEXT NOT NULL,
    realized_pnl_inr TEXT NOT NULL DEFAULT '0',
    decision_bar_ms INTEGER NOT NULL,
    loop_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    UNIQUE(market, decision_bar_ms, action)
);
CREATE TABLE IF NOT EXISTS positions (
    market TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,
    qty TEXT NOT NULL,
    avg_entry TEXT NOT NULL,
    quote_ccy TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    opened_bar_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    loop_id INTEGER NOT NULL,
    cash_inr TEXT NOT NULL,
    mtm_inr TEXT NOT NULL,
    equity_inr TEXT NOT NULL,
    daily_pnl_inr TEXT NOT NULL,
    notes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _d(value: str | Decimal) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class Fill:
    id: int
    ts_utc: str
    market: str
    pair: str
    side: str
    action: str
    qty: Decimal
    price: Decimal
    quote_ccy: str
    notional_quote: Decimal
    notional_inr: Decimal
    fee_quote: Decimal
    fee_inr: Decimal
    usdt_inr: Decimal
    realized_pnl_inr: Decimal
    decision_bar_ms: int
    loop_id: int
    reason: str


@dataclass(frozen=True)
class Position:
    market: str
    pair: str
    side: str
    qty: Decimal
    avg_entry: Decimal
    quote_ccy: str
    opened_at: str
    opened_bar_ms: int


@dataclass(frozen=True)
class Snapshot:
    ts_utc: str
    loop_id: int
    cash_inr: Decimal
    mtm_inr: Decimal
    equity_inr: Decimal
    daily_pnl_inr: Decimal
    notes: str


class Ledger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def init_bankroll(self, amount_inr: Decimal) -> None:
        if self.get_meta("cash_inr") is None:
            self.set_meta("cash_inr", str(amount_inr))
            self.set_meta("starting_bankroll_inr", str(amount_inr))
            self.set_meta("loop_id", "0")

    @property
    def cash_inr(self) -> Decimal:
        return _d(self.get_meta("cash_inr", "0") or "0")

    def set_cash(self, amount: Decimal) -> None:
        self.set_meta("cash_inr", str(amount))

    def next_loop_id(self) -> int:
        current = int(self.get_meta("loop_id", "0") or "0")
        nxt = current + 1
        self.set_meta("loop_id", str(nxt))
        return nxt

    def already_acted(self, market: str, decision_bar_ms: int, action: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM fills WHERE market=? AND decision_bar_ms=? AND action=?",
            (market, decision_bar_ms, action),
        ).fetchone()
        return row is not None

    def insert_fill(self, **kwargs: Any) -> int | None:
        cols = [
            "ts_utc",
            "market",
            "pair",
            "side",
            "action",
            "qty",
            "price",
            "quote_ccy",
            "notional_quote",
            "notional_inr",
            "fee_quote",
            "fee_inr",
            "usdt_inr",
            "realized_pnl_inr",
            "decision_bar_ms",
            "loop_id",
            "reason",
        ]
        values = [kwargs[c] if not isinstance(kwargs[c], Decimal) else str(kwargs[c]) for c in cols]
        try:
            cur = self._conn.execute(
                f"INSERT INTO fills({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                values,
            )
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            self._conn.rollback()
            return None

    def upsert_position(self, pos: Position) -> None:
        self._conn.execute(
            """
            INSERT INTO positions(market, pair, side, qty, avg_entry, quote_ccy, opened_at, opened_bar_ms)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(market) DO UPDATE SET
                pair=excluded.pair, side=excluded.side, qty=excluded.qty,
                avg_entry=excluded.avg_entry, quote_ccy=excluded.quote_ccy,
                opened_at=excluded.opened_at, opened_bar_ms=excluded.opened_bar_ms
            """,
            (
                pos.market,
                pos.pair,
                pos.side,
                str(pos.qty),
                str(pos.avg_entry),
                pos.quote_ccy,
                pos.opened_at,
                pos.opened_bar_ms,
            ),
        )
        self._conn.commit()

    def delete_position(self, market: str) -> None:
        self._conn.execute("DELETE FROM positions WHERE market=?", (market,))
        self._conn.commit()

    def positions(self) -> list[Position]:
        rows = self._conn.execute("SELECT * FROM positions ORDER BY market").fetchall()
        return [self._pos(row) for row in rows]

    def get_position(self, market: str) -> Position | None:
        row = self._conn.execute("SELECT * FROM positions WHERE market=?", (market,)).fetchone()
        return self._pos(row) if row else None

    def fills(self, limit: int = 50) -> list[Fill]:
        rows = self._conn.execute("SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._fill(row) for row in rows]

    def exit_fills(self) -> list[Fill]:
        rows = self._conn.execute("SELECT * FROM fills WHERE action='exit' ORDER BY id").fetchall()
        return [self._fill(row) for row in rows]

    def trade_samples(self) -> list[TradeSample]:
        samples: list[TradeSample] = []
        for fill in self.exit_fills():
            pnl = fill.realized_pnl_inr
            samples.append(TradeSample(win=pnl > 0, pnl_inr=pnl))
        return samples

    def add_snapshot(self, snap: Snapshot) -> None:
        self._conn.execute(
            """
            INSERT INTO snapshots(ts_utc, loop_id, cash_inr, mtm_inr, equity_inr, daily_pnl_inr, notes)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                snap.ts_utc,
                snap.loop_id,
                str(snap.cash_inr),
                str(snap.mtm_inr),
                str(snap.equity_inr),
                str(snap.daily_pnl_inr),
                snap.notes,
            ),
        )
        self._conn.commit()

    def latest_snapshot(self) -> Snapshot | None:
        row = self._conn.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return Snapshot(
            ts_utc=row["ts_utc"],
            loop_id=int(row["loop_id"]),
            cash_inr=_d(row["cash_inr"]),
            mtm_inr=_d(row["mtm_inr"]),
            equity_inr=_d(row["equity_inr"]),
            daily_pnl_inr=_d(row["daily_pnl_inr"]),
            notes=row["notes"],
        )

    def add_event(self, level: str, message: str) -> None:
        self._conn.execute(
            "INSERT INTO events(ts_utc, level, message) VALUES(?,?,?)",
            (_now(), level, message),
        )
        self._conn.commit()

    def recent_events(self, limit: int = 20) -> list[tuple[str, str, str]]:
        rows = self._conn.execute(
            "SELECT ts_utc, level, message FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(r["ts_utc"], r["level"], r["message"]) for r in rows]

    @staticmethod
    def _pos(row: sqlite3.Row) -> Position:
        return Position(
            market=row["market"],
            pair=row["pair"],
            side=row["side"],
            qty=_d(row["qty"]),
            avg_entry=_d(row["avg_entry"]),
            quote_ccy=row["quote_ccy"],
            opened_at=row["opened_at"],
            opened_bar_ms=int(row["opened_bar_ms"]),
        )

    @staticmethod
    def _fill(row: sqlite3.Row) -> Fill:
        return Fill(
            id=int(row["id"]),
            ts_utc=row["ts_utc"],
            market=row["market"],
            pair=row["pair"],
            side=row["side"],
            action=row["action"],
            qty=_d(row["qty"]),
            price=_d(row["price"]),
            quote_ccy=row["quote_ccy"],
            notional_quote=_d(row["notional_quote"]),
            notional_inr=_d(row["notional_inr"]),
            fee_quote=_d(row["fee_quote"]),
            fee_inr=_d(row["fee_inr"]),
            usdt_inr=_d(row["usdt_inr"]),
            realized_pnl_inr=_d(row["realized_pnl_inr"]),
            decision_bar_ms=int(row["decision_bar_ms"]),
            loop_id=int(row["loop_id"]),
            reason=row["reason"],
        )
