from __future__ import annotations

from pathlib import Path

from paperbot.broker.ledger import Ledger
from paperbot.broker.paper import PaperBroker
from paperbot.config import Settings
from paperbot.loop import run_once
from paperbot.market.fixtures import FixtureMarketSource, write_synthetic_fixture
from paperbot.strategy.momentum import MomentumStrategy


def test_fixture_loop_records_paper_fills(tmp_path: Path) -> None:
    fixture = tmp_path / "synth.json"
    write_synthetic_fixture(fixture)
    settings = Settings(
        ledger_path=tmp_path / "ledger.sqlite",
        data_source="fixture",
        fixture_path=fixture,
        pairs=("BTCUSDT", "ETHUSDT"),
        max_open_positions=2,
        mom_lookback=15,
        mom_entry_ret=0.0025,
        mom_volume_mult=1.2,
        mom_take_pct=0.006,
        mom_stop_pct=0.05,
        mom_max_hold_bars=20,
        scan_interval_sec=1,
        kill_file=tmp_path / "KILL",
        status_path=tmp_path / "status.json",
        log_path=tmp_path / "bot.log",
    )
    ledger = Ledger(settings.ledger_path)
    broker = PaperBroker(ledger, settings)
    strategy = MomentumStrategy(settings)
    source = FixtureMarketSource(fixture)

    saw_fill = False
    for _ in range(25):
        status = run_once(
            settings=settings,
            ledger=ledger,
            broker=broker,
            strategy=strategy,
            source=source,
        )
        if status["actions"] or ledger.fills():
            saw_fill = True
            break
    assert saw_fill, "synthetic momentum fixture should produce at least one paper fill"
    assert ledger.latest_snapshot() is not None
    assert Path(settings.status_path).is_file()
