"""CoinDCX public REST client. No API keys. Paper-phase market data only.

Verified 2026-09-21 against https://docs.coindcx.com/ and live:
  GET https://api.coindcx.com/exchange/ticker
  GET https://api.coindcx.com/exchange/v1/markets_details
  GET https://api.coindcx.com/market_data/candles?pair=B-BTC_USDT&interval=1m
  GET https://api.coindcx.com/market_data/orderbook?pair=B-BTC_USDT
Ticker `market` is BTCUSDT; candles/orderbook `pair` is B-BTC_USDT (ecode-target_quote).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Protocol

from paperbot.httputil import PoliteHttp
from paperbot.market.models import Candle, MarketInfo, OrderBook, Ticker

log = logging.getLogger("paperbot.market")

# Fallback if markets_details is down. ecode B = Binance-routed USDT, I = INR.
FALLBACK_PAIRS = {
    "BTCUSDT": "B-BTC_USDT",
    "ETHUSDT": "B-ETH_USDT",
    "SOLUSDT": "B-SOL_USDT",
    "XRPUSDT": "B-XRP_USDT",
    "BTCINR": "I-BTC_INR",
    "ETHINR": "I-ETH_INR",
    "USDTINR": "I-USDT_INR",
}


class MarketSource(Protocol):
    def get_tickers(self) -> dict[str, Ticker]: ...
    def get_candles(self, pair: str, interval: str, limit: int) -> list[Candle]: ...
    def get_orderbook(self, pair: str, depth: int = 20) -> OrderBook: ...
    def get_markets_details(self) -> dict[str, MarketInfo]: ...
    def resolve_pair(self, market: str) -> str: ...


class CoinDCXPublicClient:
    def __init__(self, http: PoliteHttp, base_url: str = "https://api.coindcx.com") -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._markets: dict[str, MarketInfo] | None = None

    def get_tickers(self) -> dict[str, Ticker]:
        payload = self.http.get_json(f"{self.base_url}/exchange/ticker")
        if not isinstance(payload, list):
            raise RuntimeError("unexpected ticker payload")
        out: dict[str, Ticker] = {}
        for row in payload:
            try:
                ticker = Ticker.from_api(row)
            except (KeyError, ValueError, TypeError):
                continue
            out[ticker.market] = ticker
        return out

    def get_markets_details(self) -> dict[str, MarketInfo]:
        if self._markets is not None:
            return self._markets
        payload = self.http.get_json(f"{self.base_url}/exchange/v1/markets_details")
        markets: dict[str, MarketInfo] = {}
        if isinstance(payload, list):
            for row in payload:
                try:
                    info = MarketInfo.from_api(row)
                except (KeyError, ValueError, TypeError):
                    continue
                markets[info.coindcx_name] = info
        self._markets = markets
        return markets

    def resolve_pair(self, market: str) -> str:
        market = market.upper()
        details = self.get_markets_details()
        if market in details:
            return details[market].pair
        if market in FALLBACK_PAIRS:
            return FALLBACK_PAIRS[market]
        raise KeyError(f"unknown market {market}; not in markets_details or fallback map")

    def get_candles(self, pair: str, interval: str, limit: int) -> list[Candle]:
        payload = self.http.get_json(
            f"{self.base_url}/market_data/candles",
            params={"pair": pair, "interval": interval, "limit": min(limit, 1000)},
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"unexpected candles payload for {pair}")
        candles = [Candle.from_api(row) for row in payload]
        candles.sort(key=lambda c: c.time_ms)
        return candles

    def get_orderbook(self, pair: str, depth: int = 20) -> OrderBook:
        payload = self.http.get_json(
            f"{self.base_url}/market_data/orderbook",
            params={"pair": pair, "depth": depth},
        )
        if not isinstance(payload, dict):
            raise RuntimeError(f"unexpected orderbook payload for {pair}")
        bids = payload.get("bids") or {}
        asks = payload.get("asks") or {}
        best_bid = max((float(k) for k in bids), default=None)
        best_ask = min((float(k) for k in asks), default=None)

        return OrderBook(
            pair=pair,
            timestamp_ms=int(payload.get("timestamp") or 0),
            best_bid=Decimal(str(best_bid)) if best_bid is not None else None,
            best_ask=Decimal(str(best_ask)) if best_ask is not None else None,
        )
