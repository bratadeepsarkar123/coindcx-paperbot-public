from __future__ import annotations

from paperbot.config import Settings
from paperbot.market.models import Candle
from paperbot.strategy.momentum import Action, MomentumStrategy, Side


def _candles_from(prices: list[float], volumes: list[float] | None = None) -> list[Candle]:
    vols = volumes or [3.0] * len(prices)
    out = []
    for i, px in enumerate(prices):
        out.append(
            Candle(open=px, high=px, low=px, close=px, volume=vols[i], time_ms=1_000_000 + i * 60_000)
        )
    return out


def test_momentum_long_entry_with_volume() -> None:
    settings = Settings(mom_lookback=5, mom_entry_ret=0.01, mom_volume_mult=1.5, mom_exit_ret=0.0)
    strat = MomentumStrategy(settings)
    # 10 quiet + 5 up-bars. Extra dummy newest bar is dropped as in-progress.
    prices = [100.0] * 10 + [101.0, 102.0, 103.0, 104.0, 105.2, 105.2]
    vols = [2.0] * 10 + [8.0, 8.0, 8.0, 8.0, 8.0, 8.0]
    sig = strat.evaluate(_candles_from(prices, vols), None)
    assert sig.action is Action.ENTER
    assert sig.side is Side.LONG


def test_no_entry_without_volume() -> None:
    settings = Settings(mom_lookback=5, mom_entry_ret=0.01, mom_volume_mult=1.5)
    strat = MomentumStrategy(settings)
    prices = [100.0] * 10 + [101.0, 102.0, 103.0, 104.0, 105.2, 105.2]
    vols = [2.0] * 16
    sig = strat.evaluate(_candles_from(prices, vols), None)
    assert sig.action is Action.HOLD


def test_insufficient_history_holds() -> None:
    strat = MomentumStrategy(Settings(mom_lookback=15))
    sig = strat.evaluate(_candles_from([1.0, 1.1, 1.2]), None)
    assert sig.action is Action.HOLD
    assert "insufficient" in sig.reason
