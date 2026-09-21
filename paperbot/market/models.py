from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float
    time_ms: int

    @classmethod
    def from_api(cls, row: dict) -> Candle:
        return cls(
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume") or 0.0),
            time_ms=int(row["time"]),
        )


@dataclass(frozen=True)
class Ticker:
    market: str
    last_price: Decimal
    bid: Decimal | None
    ask: Decimal | None
    volume: Decimal
    change_24_hour: float
    timestamp_ms: int

    @classmethod
    def from_api(cls, row: dict) -> Ticker:
        bid_raw = row.get("bid")
        ask_raw = row.get("ask")
        return cls(
            market=str(row["market"]).upper(),
            last_price=Decimal(str(row["last_price"])),
            bid=Decimal(str(bid_raw)) if bid_raw not in (None, "") else None,
            ask=Decimal(str(ask_raw)) if ask_raw not in (None, "") else None,
            volume=Decimal(str(row.get("volume") or "0")),
            change_24_hour=float(row.get("change_24_hour") or 0.0),
            timestamp_ms=int(row.get("timestamp") or 0),
        )

    @property
    def mid(self) -> Decimal:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / Decimal("2")
        return self.last_price


@dataclass(frozen=True)
class MarketInfo:
    coindcx_name: str
    pair: str
    ecode: str
    status: str
    base_currency: str  # quote, e.g. USDT or INR
    target_currency: str  # base asset, e.g. BTC
    min_quantity: Decimal
    min_notional: Decimal

    @classmethod
    def from_api(cls, row: dict) -> MarketInfo:
        return cls(
            coindcx_name=str(row["coindcx_name"]).upper(),
            pair=str(row["pair"]),
            ecode=str(row.get("ecode") or ""),
            status=str(row.get("status") or ""),
            base_currency=str(row.get("base_currency_short_name") or "").upper(),
            target_currency=str(row.get("target_currency_short_name") or "").upper(),
            min_quantity=Decimal(str(row.get("min_quantity") or "0")),
            min_notional=Decimal(str(row.get("min_notional") or "0")),
        )


@dataclass(frozen=True)
class OrderBook:
    pair: str
    timestamp_ms: int
    best_bid: Decimal | None
    best_ask: Decimal | None
