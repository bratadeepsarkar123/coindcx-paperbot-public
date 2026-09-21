"""Kill file + daily paper-loss circuit breaker + max open positions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from paperbot.broker.ledger import Ledger
from paperbot.config import Settings

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class RiskDecision:
    allow_entries: bool
    flatten: bool
    reason: str


def ist_today() -> str:
    return datetime.now(IST).date().isoformat()


def kill_file_present(path: Path) -> bool:
    return path.exists()


def rollover_daily_equity(ledger: Ledger, equity: Decimal) -> None:
    today = ist_today()
    stored_day = ledger.get_meta("day_ist")
    if stored_day != today:
        ledger.set_meta("day_ist", today)
        ledger.set_meta("day_start_equity", str(equity))
        ledger.set_meta("breaker_tripped", "0")


def assess(
    *,
    settings: Settings,
    ledger: Ledger,
    equity: Decimal,
    open_count: int,
) -> RiskDecision:
    if kill_file_present(settings.kill_file):
        return RiskDecision(False, True, f"kill file present: {settings.kill_file}")

    rollover_daily_equity(ledger, equity)
    if ledger.get_meta("breaker_tripped") == "1":
        return RiskDecision(False, True, "daily loss breaker latched (IST)")

    start = Decimal(ledger.get_meta("day_start_equity", str(equity)) or str(equity))
    if start > 0:
        loss_pct = (start - equity) / start
        if loss_pct >= settings.max_daily_loss_pct:
            ledger.set_meta("breaker_tripped", "1")
            return RiskDecision(
                False,
                True,
                f"daily loss breaker {loss_pct:.2%} >= {settings.max_daily_loss_pct:.2%}",
            )

    if open_count >= settings.max_open_positions:
        # Entries are still gated per-fill using live open count (exits this loop free slots).
        return RiskDecision(True, False, f"max open positions {open_count}/{settings.max_open_positions}")

    return RiskDecision(True, False, "ok")


def write_kill(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("killed\n", encoding="utf-8")


def clear_kill(path: Path) -> None:
    if path.exists():
        path.unlink()
