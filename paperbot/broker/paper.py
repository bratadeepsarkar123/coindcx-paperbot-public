"""Paper broker: hypothetical fills only. Never talks to CoinDCX order APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from paperbot.broker.ledger import Ledger, Position, Snapshot
from paperbot.config import Settings
from paperbot.sizer.kelly import apply_slippage, fee_on_notional, qty_from_notional, round_inr


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class FillResult:
    ok: bool
    message: str
    fill_id: int | None = None


class PaperBroker:
    name = "paper"

    def __init__(self, ledger: Ledger, settings: Settings) -> None:
        self.ledger = ledger
        self.settings = settings
        self.ledger.init_bankroll(settings.paper_bankroll_inr)

    def mark_to_market(
        self,
        marks_quote: dict[str, Decimal],
        usdt_inr: Decimal,
        loop_id: int,
        notes: str = "",
    ) -> Snapshot:
        cash = self.ledger.cash_inr
        unreal = Decimal("0")
        inventory = Decimal("0")
        for pos in self.ledger.positions():
            mark = marks_quote.get(pos.market)
            if mark is None:
                mark = pos.avg_entry
            fx = Decimal("1") if pos.quote_ccy == "INR" else usdt_inr
            signed = Decimal("1") if pos.side == "long" else Decimal("-1")
            inventory += pos.qty * mark * fx * signed
            unreal += (mark - pos.avg_entry) * pos.qty * signed * fx
        equity = cash + inventory
        day_start = Decimal(self.ledger.get_meta("day_start_equity", str(equity)) or str(equity))
        daily = equity - day_start
        snap = Snapshot(
            ts_utc=_now(),
            loop_id=loop_id,
            cash_inr=round_inr(cash),
            mtm_inr=round_inr(unreal),
            equity_inr=round_inr(equity),
            daily_pnl_inr=round_inr(daily),
            notes=notes,
        )
        self.ledger.add_snapshot(snap)
        return snap

    def enter_long(
        self,
        *,
        market: str,
        pair: str,
        quote_ccy: str,
        price: Decimal,
        notional_inr: Decimal,
        usdt_inr: Decimal,
        decision_bar_ms: int,
        loop_id: int,
        reason: str,
    ) -> FillResult:
        if self.ledger.get_position(market) is not None:
            return FillResult(False, f"{market} already open")
        if self.ledger.already_acted(market, decision_bar_ms, "entry"):
            return FillResult(False, f"{market} entry already recorded for bar {decision_bar_ms}")

        fill_price = apply_slippage(price, "buy", self.settings.slippage_bps)
        fx = Decimal("1") if quote_ccy == "INR" else usdt_inr
        if fx <= 0:
            return FillResult(False, "bad FX")
        notional_quote = notional_inr / fx
        fee_quote = fee_on_notional(notional_quote, self.settings.fee_bps, self.settings.fee_gst_pct)
        fee_inr = fee_quote * fx
        qty = qty_from_notional(notional_quote, fill_price)
        if qty <= 0:
            return FillResult(False, "qty rounded to zero")

        debit = notional_inr + fee_inr
        cash = self.ledger.cash_inr
        if debit > cash:
            return FillResult(False, f"insufficient paper cash {cash} < {debit}")

        fill_id = self.ledger.insert_fill(
            ts_utc=_now(),
            market=market,
            pair=pair,
            side="buy",
            action="entry",
            qty=qty,
            price=fill_price,
            quote_ccy=quote_ccy,
            notional_quote=notional_quote,
            notional_inr=notional_inr,
            fee_quote=fee_quote,
            fee_inr=fee_inr,
            usdt_inr=fx,
            realized_pnl_inr=Decimal("0"),
            decision_bar_ms=decision_bar_ms,
            loop_id=loop_id,
            reason=reason,
        )
        if fill_id is None:
            return FillResult(False, "duplicate entry ignored (idempotent)")

        self.ledger.set_cash(cash - debit)
        self.ledger.upsert_position(
            Position(
                market=market,
                pair=pair,
                side="long",
                qty=qty,
                avg_entry=fill_price,
                quote_ccy=quote_ccy,
                opened_at=_now(),
                opened_bar_ms=decision_bar_ms,
            )
        )
        return FillResult(True, f"bought {qty} {market} @ {fill_price}", fill_id)

    def exit(
        self,
        *,
        market: str,
        price: Decimal,
        usdt_inr: Decimal,
        decision_bar_ms: int,
        loop_id: int,
        reason: str,
    ) -> FillResult:
        pos = self.ledger.get_position(market)
        if pos is None:
            return FillResult(False, f"no position {market}")
        if self.ledger.already_acted(market, decision_bar_ms, "exit"):
            return FillResult(False, f"{market} exit already recorded for bar {decision_bar_ms}")

        side = "sell" if pos.side == "long" else "buy"
        fill_price = apply_slippage(price, side, self.settings.slippage_bps)
        fx = Decimal("1") if pos.quote_ccy == "INR" else usdt_inr
        notional_quote = fill_price * pos.qty
        notional_inr = notional_quote * fx
        fee_quote = fee_on_notional(notional_quote, self.settings.fee_bps, self.settings.fee_gst_pct)
        fee_inr = fee_quote * fx
        direction = Decimal("1") if pos.side == "long" else Decimal("-1")
        gross = (fill_price - pos.avg_entry) * pos.qty * direction * fx
        # Entry fee already hit cash; exit fee hits realized. Gross MTM vs entry, minus this exit fee.
        realized = gross - fee_inr

        fill_id = self.ledger.insert_fill(
            ts_utc=_now(),
            market=market,
            pair=pos.pair,
            side=side,
            action="exit",
            qty=pos.qty,
            price=fill_price,
            quote_ccy=pos.quote_ccy,
            notional_quote=notional_quote,
            notional_inr=notional_inr,
            fee_quote=fee_quote,
            fee_inr=fee_inr,
            usdt_inr=fx,
            realized_pnl_inr=realized,
            decision_bar_ms=decision_bar_ms,
            loop_id=loop_id,
            reason=reason,
        )
        if fill_id is None:
            return FillResult(False, "duplicate exit ignored (idempotent)")

        proceeds = notional_inr - fee_inr
        self.ledger.set_cash(self.ledger.cash_inr + proceeds)
        self.ledger.delete_position(market)
        return FillResult(True, f"closed {market} realized ₹{realized}", fill_id)
