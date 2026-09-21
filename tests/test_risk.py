from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from paperbot.broker.ledger import Ledger
from paperbot.config import Settings
from paperbot.risk.controls import assess, write_kill


def test_kill_file_blocks_and_flattens(tmp_path: Path) -> None:
    kill = tmp_path / "KILL"
    write_kill(kill)
    settings = Settings(kill_file=kill, max_daily_loss_pct=Decimal("0.03"), max_open_positions=2)
    ledger = Ledger(tmp_path / "l.sqlite")
    ledger.init_bankroll(Decimal("100000"))
    d = assess(settings=settings, ledger=ledger, equity=Decimal("100000"), open_count=0)
    assert d.allow_entries is False
    assert d.flatten is True
    assert "kill file" in d.reason


def test_breaker_latches_for_the_ist_day(tmp_path: Path) -> None:
    settings = Settings(kill_file=tmp_path / "nope", max_daily_loss_pct=Decimal("0.03"), max_open_positions=4)
    ledger = Ledger(tmp_path / "l.sqlite")
    ledger.init_bankroll(Decimal("100000"))
    d1 = assess(settings=settings, ledger=ledger, equity=Decimal("100000"), open_count=0)
    assert d1.allow_entries is True
    d2 = assess(settings=settings, ledger=ledger, equity=Decimal("96000"), open_count=0)
    assert d2.flatten is True
    # equity recovered but same IST day — stay halted
    d3 = assess(settings=settings, ledger=ledger, equity=Decimal("101000"), open_count=0)
    assert d3.allow_entries is False
    assert "latched" in d3.reason


def test_max_open_positions(tmp_path: Path) -> None:
    settings = Settings(kill_file=tmp_path / "nope", max_open_positions=1, max_daily_loss_pct=Decimal("0.5"))
    ledger = Ledger(tmp_path / "l.sqlite")
    ledger.init_bankroll(Decimal("100000"))
    d = assess(settings=settings, ledger=ledger, equity=Decimal("100000"), open_count=1)
    assert d.flatten is False
    assert "max open" in d.reason
