# CoinDCX public API notes (checked 2026-09-21)

Docs: https://docs.coindcx.com/  
Base URL used here: `https://api.coindcx.com`  
(Some futures endpoints use `https://public.coindcx.com`; this bot is **spot paper**.)

No authentication for the endpoints we call. Private order/balance endpoints are POST + HMAC and are **not implemented**.

## Endpoints in use

| Purpose | Method | Path | Notes |
| --- | --- | --- |
| All tickers | GET | `/exchange/ticker` | `market` = `BTCUSDT`. Fields: `last_price`, `bid`, `ask`, `volume`, `change_24_hour`, `timestamp` |
| Market metadata | GET | `/exchange/v1/markets_details` | `coindcx_name`, `pair` (`B-BTC_USDT`), `min_notional`, quote = `base_currency_short_name` |
| Candles | GET | `/market_data/candles` | Query: `pair`, `interval` (`1m`,`15m`,`1h`,`1d`), `limit` (max 1000). Newest-first from API; we sort ascending. |
| Order book | GET | `/market_data/orderbook` | Optional (`USE_ORDERBOOK=false` by default to stay polite) |

## Pair naming

Ticker/market name: `BTCUSDT`, `ETHINR`.  
Candle/orderbook `pair`: `{ecode}-{BASE}_{QUOTE}`, e.g. `B-BTC_USDT`, `I-BTC_INR`, `I-USDT_INR`.

INR FX for USDT marks: ticker `USDTINR` (live last ≈ ₹99.6 when probed).

## Rate limits

Documented SPOT limits in the official table are for **authenticated order APIs**. Public GETs are not listed with a number there. This client still spaces requests (`MIN_REQUEST_INTERVAL_SEC=0.25`) and exponential-backs off on **HTTP 429** and 5xx (cap 30s). Default loop: 1 ticker + 4 candle calls every 120s.

## Fees (model, not billed)

CoinDCX spot taker is VIP-tiered; public pages cite ~**0.10–0.20%** plus **18% GST on the fee**. Default paper model: `FEE_BPS=20`, `FEE_GST_PCT=18`. Round-trip ≈ 47.2 bps before slippage.

## WebSocket

Official sockets exist (candles, depth, trades) via socket.io v2. Phase-1 stays on REST for simplicity and Azure friendliness. Do not need them to paper-trade on a 1–5 minute cadence.
