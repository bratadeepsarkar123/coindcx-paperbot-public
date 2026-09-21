"""Short-horizon momentum + volume confirmation (Phase-1, one strategy)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from paperbot.config import Settings
from paperbot.market.models import Candle


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class Action(str, Enum):
    HOLD = "hold"
    ENTER = "enter"
    EXIT = "exit"


@dataclass(frozen=True)
class Signal:
    action: Action
    side: Side | None
    lookback_return: float
    volume_ratio: float
    reason: str
    decision_bar_ms: int
    close: float

    @property
    def is_entry(self) -> bool:
        return self.action is Action.ENTER

    @property
    def is_exit(self) -> bool:
        return self.action is Action.EXIT


@dataclass(frozen=True)
class OpenPositionView:
    market: str
    side: Side
    entry_price: float
    opened_bar_ms: int
    bars_held: int
    last_close: float


def _closed_candles(candles: list[Candle], interval: str) -> list[Candle]:
    """Drop the newest bar so we never trade an in-progress candle."""
    if len(candles) < 3:
        return candles
    # API already returns completed-ish bars; still ignore the latest to be safe.
    return candles[:-1]


def _lookback_return(closes: list[float], lookback: int) -> float:
    if len(closes) < lookback + 1 or closes[-1 - lookback] <= 0:
        return 0.0
    return closes[-1] / closes[-1 - lookback] - 1.0


def _volume_ratio(volumes: list[float], lookback: int, recent: int = 3) -> float:
    """Recent volume vs the prior lookback window (excludes the recent bars)."""
    need = lookback + recent
    if len(volumes) < need:
        return 1.0
    baseline = volumes[-(lookback + recent) : -recent]
    tail = volumes[-recent:]
    base = sum(baseline) / len(baseline)
    if base <= 0:
        return 1.0
    return (sum(tail) / len(tail)) / base


class MomentumStrategy:
    """Continuation after a short, volume-confirmed return.

    Edge hypothesis is documented in docs/strategy.md. Long-only by default
    because CoinDCX spot cannot short without futures (authenticated).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        candles: list[Candle],
        position: OpenPositionView | None,
    ) -> Signal:
        closed = _closed_candles(candles, self.settings.candle_interval)
        lookback = self.settings.mom_lookback
        if len(closed) < lookback + 2:
            last_ms = closed[-1].time_ms if closed else 0
            last_close = closed[-1].close if closed else 0.0
            return Signal(Action.HOLD, None, 0.0, 0.0, "insufficient_candles", last_ms, last_close)

        closes = [c.close for c in closed]
        volumes = [c.volume for c in closed]
        last = closed[-1]
        ret = _lookback_return(closes, lookback)
        vol_ratio = _volume_ratio(volumes, lookback)
        vol_ok = vol_ratio >= self.settings.mom_volume_mult

        if position is not None:
            return self._maybe_exit(position, last, ret, vol_ratio)

        if ret >= self.settings.mom_entry_ret and vol_ok:
            return Signal(
                Action.ENTER,
                Side.LONG,
                ret,
                vol_ratio,
                f"momentum_long ret={ret:.4%} vol={vol_ratio:.2f}",
                last.time_ms,
                last.close,
            )
        if (
            self.settings.allow_shorts
            and ret <= -self.settings.mom_entry_ret
            and vol_ok
        ):
            return Signal(
                Action.ENTER,
                Side.SHORT,
                ret,
                vol_ratio,
                f"momentum_short ret={ret:.4%} vol={vol_ratio:.2f}",
                last.time_ms,
                last.close,
            )

        if abs(ret) >= self.settings.mom_entry_ret * 0.5:
            reason = f"near_miss ret={ret:.4%} vol={vol_ratio:.2f} (need {self.settings.mom_entry_ret:.4%} & vol>={self.settings.mom_volume_mult})"
        else:
            reason = f"no_edge ret={ret:.4%} vol={vol_ratio:.2f}"
        return Signal(Action.HOLD, None, ret, vol_ratio, reason, last.time_ms, last.close)

    def _maybe_exit(
        self,
        position: OpenPositionView,
        last: Candle,
        ret: float,
        vol_ratio: float,
    ) -> Signal:
        move = last.close / position.entry_price - 1.0
        if position.side is Side.SHORT:
            move = -move

        if move <= -self.settings.mom_stop_pct:
            return Signal(Action.EXIT, position.side, ret, vol_ratio, f"stop move={move:.4%}", last.time_ms, last.close)
        if move >= self.settings.mom_take_pct:
            return Signal(Action.EXIT, position.side, ret, vol_ratio, f"take move={move:.4%}", last.time_ms, last.close)
        if position.bars_held >= self.settings.mom_max_hold_bars:
            return Signal(Action.EXIT, position.side, ret, vol_ratio, f"time_stop bars={position.bars_held}", last.time_ms, last.close)

        # Momentum fade: lookback return no longer supports the position.
        if position.side is Side.LONG and ret <= self.settings.mom_exit_ret:
            return Signal(Action.EXIT, position.side, ret, vol_ratio, f"fade ret={ret:.4%}", last.time_ms, last.close)
        if position.side is Side.SHORT and ret >= -self.settings.mom_exit_ret:
            return Signal(Action.EXIT, position.side, ret, vol_ratio, f"fade ret={ret:.4%}", last.time_ms, last.close)

        return Signal(Action.HOLD, position.side, ret, vol_ratio, f"hold move={move:.4%}", last.time_ms, last.close)
