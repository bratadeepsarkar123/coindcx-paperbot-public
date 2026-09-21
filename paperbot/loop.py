"""Idempotent paper trading loop. Always uses PaperBroker."""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Any

from paperbot.broker.ledger import Ledger, Position
from paperbot.broker.live_stub import assert_paper_only
from paperbot.broker.paper import PaperBroker
from paperbot.config import Settings
from paperbot.httputil import PoliteHttp
from paperbot.market.client import CoinDCXPublicClient, MarketSource
from paperbot.market.fixtures import FixtureMarketSource
from paperbot.market.models import MarketInfo, Ticker
from paperbot.risk.controls import assess
from paperbot.sizer.kelly import estimate_p_and_b, size_notional_inr
from paperbot.strategy.momentum import MomentumStrategy, OpenPositionView, Side

log = logging.getLogger("paperbot.loop")

INTERVAL_MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "1d": 86_400_000}


def build_market_source(settings: Settings) -> MarketSource:
    if settings.data_source == "fixture":
        path = settings.fixture_path
        if not path.is_file():
            path = settings.project_root / path
        log.warning("DATA_SOURCE=fixture using %s", path)
        return FixtureMarketSource(path)
    http = PoliteHttp(
        timeout_sec=settings.request_timeout_sec,
        min_interval_sec=settings.min_request_interval_sec,
    )
    return CoinDCXPublicClient(http, base_url=settings.base_url)


def usdt_inr_rate(tickers: dict[str, Ticker], fallback: Decimal) -> Decimal:
    t = tickers.get("USDTINR")
    if t is not None and t.last_price > 0:
        return t.last_price
    return fallback


def quote_mark(ticker: Ticker | None, fallback: Decimal) -> Decimal:
    if ticker is None:
        return fallback
    return ticker.last_price


def bars_held(pos: Position, last_bar_ms: int, interval: str) -> int:
    step = INTERVAL_MS.get(interval, 60_000)
    if step <= 0:
        return 0
    return max(0, int((last_bar_ms - pos.opened_bar_ms) // step))


def _market_info(source: MarketSource, market: str) -> MarketInfo | None:
    details = source.get_markets_details()
    return details.get(market.upper())


def run_once(
    *,
    settings: Settings,
    ledger: Ledger,
    broker: PaperBroker,
    strategy: MomentumStrategy,
    source: MarketSource,
) -> dict[str, Any]:
    assert_paper_only(settings)
    loop_id = ledger.next_loop_id()
    tickers = source.get_tickers()
    fx = usdt_inr_rate(tickers, settings.usdtinr_fallback)
    marks = {m: quote_mark(tickers.get(m), Decimal("0")) for m in settings.pairs}

    cash = ledger.cash_inr
    inventory = Decimal("0")
    for pos in ledger.positions():
        mark = marks.get(pos.market) or pos.avg_entry
        fx_pos = Decimal("1") if pos.quote_ccy == "INR" else fx
        signed = Decimal("1") if pos.side == "long" else Decimal("-1")
        inventory += pos.qty * mark * fx_pos * signed
    equity = cash + inventory
    open_count = len(ledger.positions())
    risk = assess(settings=settings, ledger=ledger, equity=equity, open_count=open_count)

    scan: list[dict[str, Any]] = []
    actions: list[str] = []

    if risk.flatten:
        for pos in list(ledger.positions()):
            mark = marks.get(pos.market) or pos.avg_entry
            result = broker.exit(
                market=pos.market,
                price=mark,
                usdt_inr=fx,
                decision_bar_ms=int(time.time() * 1000),
                loop_id=loop_id,
                reason=risk.reason,
            )
            actions.append(result.message)
            log.warning("flatten %s: %s", pos.market, result.message)

    p, b, kelly_note = estimate_p_and_b(
        ledger.trade_samples(),
        prior_p=settings.kelly_prior_p,
        prior_b=settings.kelly_prior_b,
        min_trades=settings.kelly_min_trades,
    )

    for market in settings.pairs:
        try:
            pair = source.resolve_pair(market)
            candles = source.get_candles(pair, settings.candle_interval, settings.candle_limit)
        except Exception as exc:  # noqa: BLE001 — one pair must not kill the loop
            log.exception("data error %s: %s", market, exc)
            scan.append({"market": market, "error": str(exc)})
            continue

        pos = ledger.get_position(market)
        view = None
        last_ms = candles[-2].time_ms if len(candles) >= 2 else (candles[-1].time_ms if candles else 0)
        last_close = candles[-2].close if len(candles) >= 2 else (candles[-1].close if candles else 0.0)
        if pos is not None:
            view = OpenPositionView(
                market=pos.market,
                side=Side.LONG if pos.side == "long" else Side.SHORT,
                entry_price=float(pos.avg_entry),
                opened_bar_ms=pos.opened_bar_ms,
                bars_held=bars_held(pos, last_ms, settings.candle_interval),
                last_close=last_close,
            )
        signal = strategy.evaluate(candles, view)
        row: dict[str, Any] = {
            "market": market,
            "pair": pair,
            "action": signal.action.value,
            "ret": round(signal.lookback_return, 6),
            "vol_ratio": round(signal.volume_ratio, 3),
            "reason": signal.reason,
            "bar": signal.decision_bar_ms,
            "close": signal.close,
        }

        ticker = tickers.get(market)
        mark = quote_mark(ticker, Decimal(str(signal.close or 0)))
        info = _market_info(source, market)
        quote_ccy = info.base_currency if info else ("INR" if market.endswith("INR") else "USDT")

        if signal.is_exit and pos is not None:
            result = broker.exit(
                market=market,
                price=mark,
                usdt_inr=fx,
                decision_bar_ms=signal.decision_bar_ms,
                loop_id=loop_id,
                reason=signal.reason,
            )
            row["fill"] = result.message
            actions.append(result.message)
            log.info("EXIT %s %s", market, result.message)
        elif signal.is_entry and pos is None:
            if not risk.allow_entries:
                row["fill"] = f"blocked: {risk.reason}"
                log.info("skip entry %s: %s", market, risk.reason)
            else:
                # re-check open count after fills this loop
                if len(ledger.positions()) >= settings.max_open_positions:
                    row["fill"] = "blocked: max open positions"
                else:
                    notional, f_used, size_note = size_notional_inr(
                        equity_inr=equity,
                        p=p,
                        b=b,
                        fraction=settings.effective_kelly_fraction,
                        cap=settings.kelly_cap,
                    )
                    min_notional_quote = info.min_notional if info else Decimal("5")
                    fx_pos = Decimal("1") if quote_ccy == "INR" else fx
                    min_notional_inr = min_notional_quote * fx_pos
                    if notional < min_notional_inr:
                        row["fill"] = f"notional ₹{notional} below min ₹{min_notional_inr} ({size_note})"
                    elif notional <= 0:
                        row["fill"] = f"kelly size 0 ({size_note})"
                    else:
                        result = broker.enter_long(
                            market=market,
                            pair=pair,
                            quote_ccy=quote_ccy,
                            price=mark,
                            notional_inr=notional,
                            usdt_inr=fx,
                            decision_bar_ms=signal.decision_bar_ms,
                            loop_id=loop_id,
                            reason=f"{signal.reason} | {size_note} | {kelly_note} f_used={f_used}",
                        )
                        row["fill"] = result.message
                        row["notional_inr"] = str(notional)
                        actions.append(result.message)
                        log.info("ENTRY %s %s", market, result.message)
        scan.append(row)

    snap = broker.mark_to_market(marks, fx, loop_id, notes=risk.reason)
    if isinstance(source, FixtureMarketSource):
        source.advance()

    status = {
        "owner": settings.owner,
        "mode": "PAPER",
        "broker": "paper",
        "data_source": settings.data_source,
        "loop_id": loop_id,
        "cash_inr": str(snap.cash_inr),
        "mtm_inr": str(snap.mtm_inr),
        "inventory_inr": str(snap.equity_inr - snap.cash_inr),
        "equity_inr": str(snap.equity_inr),
        "daily_pnl_inr": str(snap.daily_pnl_inr),
        "usdt_inr": str(fx),
        "open_positions": [
            {
                "market": p.market,
                "side": p.side,
                "qty": str(p.qty),
                "avg_entry": str(p.avg_entry),
            }
            for p in ledger.positions()
        ],
        "risk": risk.reason,
        "kelly": kelly_note,
        "scan": scan,
        "actions": actions,
        "ts": snap.ts_utc,
    }
    settings.status_path.parent.mkdir(parents=True, exist_ok=True)
    settings.status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    ledger.add_event("info", f"loop {loop_id} equity={snap.equity_inr} risk={risk.reason}")
    return status


def run_forever(settings: Settings, loops: int | None = None, sleep: bool = True) -> None:
    assert_paper_only(settings)
    ledger = Ledger(settings.ledger_path)
    broker = PaperBroker(ledger, settings)
    strategy = MomentumStrategy(settings)
    source = build_market_source(settings)
    n = 0
    try:
        while True:
            started = time.monotonic()
            try:
                status = run_once(
                    settings=settings,
                    ledger=ledger,
                    broker=broker,
                    strategy=strategy,
                    source=source,
                )
                log.info(
                    "loop=%s equity=₹%s daily=₹%s open=%s source=%s",
                    status["loop_id"],
                    status["equity_inr"],
                    status["daily_pnl_inr"],
                    len(status["open_positions"]),
                    settings.data_source,
                )
            except Exception:
                log.exception("loop failed; will retry")
            n += 1
            if loops is not None and n >= loops:
                break
            if not sleep:
                continue
            elapsed = time.monotonic() - started
            wait = settings.scan_interval_sec - elapsed
            if wait > 0:
                time.sleep(wait)
    finally:
        ledger.close()
