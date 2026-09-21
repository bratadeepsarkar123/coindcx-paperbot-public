"""Offline / dry-run market source. Replays recorded or synthetic candles."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from paperbot.market.client import FALLBACK_PAIRS
from paperbot.market.models import Candle, MarketInfo, OrderBook, Ticker


class FixtureMarketSource:
    """Replay growing prefixes of candles so a multi-loop run can still trade."""

    def __init__(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._tickers = {Ticker.from_api(row).market: Ticker.from_api(row) for row in payload.get("tickers", [])}
        self._candles: dict[str, list[Candle]] = {}
        self._pair_of: dict[str, str] = {}
        for market, blob in payload.get("pairs", {}).items():
            market_u = market.upper()
            self._pair_of[market_u] = blob.get("pair") or FALLBACK_PAIRS.get(market_u, market_u)
            rows = blob.get("candles") or []
            candles = [Candle.from_api(row) for row in rows]
            candles.sort(key=lambda c: c.time_ms)
            self._candles[self._pair_of[market_u]] = candles
        self._cursor = int(payload.get("start_bars") or 20)
        self._step = int(payload.get("step") or 1)
        self._markets = _default_markets()

    def advance(self) -> None:
        self._cursor += self._step

    def get_tickers(self) -> dict[str, Ticker]:
        tickers = dict(self._tickers)
        for market, pair in self._pair_of.items():
            candles = self._visible(pair)
            if not candles:
                continue
            last = Decimal(str(candles[-1].close))
            prev = tickers.get(market)
            tickers[market] = Ticker(
                market=market,
                last_price=last,
                bid=last,
                ask=last,
                volume=prev.volume if prev else Decimal("0"),
                change_24_hour=prev.change_24_hour if prev else 0.0,
                timestamp_ms=candles[-1].time_ms,
            )
        return tickers

    def get_candles(self, pair: str, interval: str, limit: int) -> list[Candle]:
        del interval
        visible = self._visible(pair)
        return visible[-limit:]

    def get_orderbook(self, pair: str, depth: int = 20) -> OrderBook:
        del depth
        candles = self._visible(pair)
        last = Decimal(str(candles[-1].close)) if candles else None
        return OrderBook(pair=pair, timestamp_ms=candles[-1].time_ms if candles else 0, best_bid=last, best_ask=last)

    def get_markets_details(self) -> dict[str, MarketInfo]:
        return self._markets

    def resolve_pair(self, market: str) -> str:
        market = market.upper()
        if market in self._pair_of:
            return self._pair_of[market]
        if market in FALLBACK_PAIRS:
            return FALLBACK_PAIRS[market]
        raise KeyError(market)

    def _visible(self, pair: str) -> list[Candle]:
        series = self._candles.get(pair, [])
        n = min(len(series), max(self._cursor, 1))
        return series[:n]


def _default_markets() -> dict[str, MarketInfo]:
    specs = [
        ("BTCUSDT", "B-BTC_USDT", "B", "USDT", "BTC", "0.00001", "5"),
        ("ETHUSDT", "B-ETH_USDT", "B", "USDT", "ETH", "0.0001", "5"),
        ("SOLUSDT", "B-SOL_USDT", "B", "USDT", "SOL", "0.001", "5"),
        ("XRPUSDT", "B-XRP_USDT", "B", "USDT", "XRP", "0.1", "5"),
        ("USDTINR", "I-USDT_INR", "I", "INR", "USDT", "0.01", "100"),
    ]
    out: dict[str, MarketInfo] = {}
    for name, pair, ecode, quote, base, min_qty, min_notional in specs:
        out[name] = MarketInfo(
            coindcx_name=name,
            pair=pair,
            ecode=ecode,
            status="active",
            base_currency=quote,
            target_currency=base,
            min_quantity=Decimal(min_qty),
            min_notional=Decimal(min_notional),
        )
    return out


def write_synthetic_fixture(path: Path) -> None:
    """Deterministic momentum burst so fixture mode produces inspectable fills."""
    interval_ms = 60_000
    start_ms = 1_700_000_000_000
    pairs = {
        "BTCUSDT": (80000.0, "B-BTC_USDT"),
        "ETHUSDT": (2600.0, "B-ETH_USDT"),
        "SOLUSDT": (110.0, "B-SOL_USDT"),
        "XRPUSDT": (1.40, "B-XRP_USDT"),
    }
    payload: dict = {"start_bars": 22, "step": 1, "interval": "1m", "pairs": {}, "tickers": []}
    for market, (px0, pair) in pairs.items():
        candles = []
        price = px0
        for i in range(70):
            # Quiet chop, then a volume-confirmed up-burst, then fade.
            if 25 <= i < 40:
                ret = 0.0009
                vol = 12.0
            elif i >= 40:
                ret = -0.00015
                vol = 4.0
            else:
                ret = 0.00002 * (1 if i % 2 == 0 else -1)
                vol = 3.0
            open_px = price
            close_px = price * (1 + ret)
            high = max(open_px, close_px) * 1.0002
            low = min(open_px, close_px) * 0.9998
            candles.append(
                {
                    "open": round(open_px, 8),
                    "high": round(high, 8),
                    "low": round(low, 8),
                    "close": round(close_px, 8),
                    "volume": vol,
                    "time": start_ms + i * interval_ms,
                }
            )
            price = close_px
        payload["pairs"][market] = {"pair": pair, "candles": candles}
        payload["tickers"].append(
            {
                "market": market,
                "last_price": str(candles[-1]["close"]),
                "bid": str(candles[-1]["close"]),
                "ask": str(candles[-1]["close"]),
                "volume": "1000",
                "change_24_hour": "1.0",
                "timestamp": candles[-1]["time"],
            }
        )
    payload["tickers"].append(
        {
            "market": "USDTINR",
            "last_price": "99.63",
            "bid": "99.62",
            "ask": "99.64",
            "volume": "1",
            "change_24_hour": "0",
            "timestamp": start_ms,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
