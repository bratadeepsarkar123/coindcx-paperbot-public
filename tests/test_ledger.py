from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from paperbot.broker.ledger import Ledger
from paperbot.broker.paper import PaperBroker
from paperbot.config import Settings
from paperbot.sizer.kelly import fee_on_notional, round_inr


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        ledger_path=tmp_path / "ledger.sqlite",
        paper_bankroll_inr=Decimal("100000"),
        fee_bps=Decimal("20"),
        fee_gst_pct=Decimal("18"),
        slippage_bps=Decimal("0"),
        kelly_cap=Decimal("0.06"),
    )


def test_entry_applies_fee_and_reduces_cash(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ledger = Ledger(settings.ledger_path)
    broker = PaperBroker(ledger, settings)

    usdt_inr = Decimal("100")
    notional_inr = Decimal("5000")
    price = Decimal("80")  # quote USDT
    result = broker.enter_long(
        market="BTCUSDT",
        pair="B-BTC_USDT",
        quote_ccy="USDT",
        price=price,
        notional_inr=notional_inr,
        usdt_inr=usdt_inr,
        decision_bar_ms=1,
        loop_id=1,
        reason="test",
    )
    assert result.ok, result.message
    fee_quote = fee_on_notional(Decimal("50"), Decimal("20"), Decimal("18"))  # 50 USDT notional
    fee_inr = fee_quote * usdt_inr
    assert ledger.cash_inr == Decimal("100000") - notional_inr - fee_inr
    pos = ledger.get_position("BTCUSDT")
    assert pos is not None
    assert pos.qty == Decimal("50") / price


def test_round_trip_fees_hit_equity(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ledger = Ledger(settings.ledger_path)
    broker = PaperBroker(ledger, settings)
    usdt_inr = Decimal("100")
    price = Decimal("50")
    notional_inr = Decimal("5000")
    broker.enter_long(
        market="ETHUSDT",
        pair="B-ETH_USDT",
        quote_ccy="USDT",
        price=price,
        notional_inr=notional_inr,
        usdt_inr=usdt_inr,
        decision_bar_ms=10,
        loop_id=1,
        reason="in",
    )
    result = broker.exit(
        market="ETHUSDT",
        price=price,
        usdt_inr=usdt_inr,
        decision_bar_ms=11,
        loop_id=2,
        reason="out",
    )
    assert result.ok, result.message
    # Two taker fees on 50 USDT = 2 * 50 * 0.002 * 1.18 * 100 INR
    expected_fee_inr = fee_on_notional(Decimal("50"), Decimal("20"), Decimal("18")) * usdt_inr * 2
    assert ledger.cash_inr == Decimal("100000") - expected_fee_inr
    assert ledger.get_position("ETHUSDT") is None
    exits = ledger.exit_fills()
    assert len(exits) == 1
    # realized includes only the exit fee (entry fee already left cash)
    assert exits[0].realized_pnl_inr == -(expected_fee_inr / 2)


def test_idempotent_duplicate_entry(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ledger = Ledger(settings.ledger_path)
    broker = PaperBroker(ledger, settings)
    kwargs = dict(
        market="SOLUSDT",
        pair="B-SOL_USDT",
        quote_ccy="USDT",
        price=Decimal("100"),
        notional_inr=Decimal("1000"),
        usdt_inr=Decimal("100"),
        decision_bar_ms=42,
        loop_id=1,
        reason="dup",
    )
    assert broker.enter_long(**kwargs).ok
    cash_after = ledger.cash_inr
    again = broker.enter_long(**kwargs)
    assert not again.ok
    assert ledger.cash_inr == cash_after
    assert len(ledger.fills()) == 1


def test_restart_restores_position_and_cash(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ledger = Ledger(settings.ledger_path)
    broker = PaperBroker(ledger, settings)
    broker.enter_long(
        market="XRPUSDT",
        pair="B-XRP_USDT",
        quote_ccy="USDT",
        price=Decimal("1.5"),
        notional_inr=Decimal("2000"),
        usdt_inr=Decimal("100"),
        decision_bar_ms=7,
        loop_id=1,
        reason="persist",
    )
    cash = ledger.cash_inr
    qty = ledger.get_position("XRPUSDT").qty
    ledger.close()

    ledger2 = Ledger(settings.ledger_path)
    assert ledger2.cash_inr == cash
    pos = ledger2.get_position("XRPUSDT")
    assert pos is not None
    assert pos.qty == qty


def test_mtm_long_unrealized(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ledger = Ledger(settings.ledger_path)
    broker = PaperBroker(ledger, settings)
    broker.enter_long(
        market="BTCUSDT",
        pair="B-BTC_USDT",
        quote_ccy="USDT",
        price=Decimal("100"),
        notional_inr=Decimal("10000"),
        usdt_inr=Decimal("100"),
        decision_bar_ms=1,
        loop_id=1,
        reason="mtm",
    )
    # price 110 USDT, qty = 100 USDT / 100 = 1, uPnL = 10 USDT * 100 = 1000 INR
    snap = broker.mark_to_market({"BTCUSDT": Decimal("110")}, Decimal("100"), loop_id=2)
    assert snap.mtm_inr == Decimal("1000.00")
    # cash lost notional+fee; inventory is 1 BTC-unit * 110 USDT * 100 INR
    fee_inr = fee_on_notional(Decimal("100"), Decimal("20"), Decimal("18")) * Decimal("100")
    assert snap.equity_inr == round_inr(Decimal("100000") - fee_inr + Decimal("1000"))
