"""Human-readable status / PnL reports."""

from __future__ import annotations

from decimal import Decimal

from paperbot.broker.ledger import Ledger
from paperbot.config import Settings
from paperbot.risk.controls import kill_file_present


def inr(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    abs_v = abs(value)
    return f"{sign}₹{abs_v:,.2f}"


def render_status(ledger: Ledger, settings: Settings) -> str:
    snap = ledger.latest_snapshot()
    start = Decimal(ledger.get_meta("starting_bankroll_inr", str(settings.paper_bankroll_inr)) or "0")
    lines = [
        "CoinDCX paper bot — Bratadeep",
        "MODE: PAPER ONLY (no live orders)",
        f"ledger: {settings.ledger_path}",
        f"kill: {'ON (' + str(settings.kill_file) + ')' if kill_file_present(settings.kill_file) else 'off'}",
        f"breaker: {ledger.get_meta('breaker_tripped', '0')}  day={ledger.get_meta('day_ist', '-')}",
        "",
    ]
    if snap is None:
        lines.append("No snapshots yet. Run: python -m paperbot run --once")
        return "\n".join(lines)

    ret = (snap.equity_inr / start - 1) if start else Decimal("0")
    inventory = snap.equity_inr - snap.cash_inr
    lines += [
        f"equity {inr(snap.equity_inr)}   start {inr(start)}   ({ret:.2%})",
        f"cash   {inr(snap.cash_inr)}   inventory {inr(inventory)}   unrealized {inr(snap.mtm_inr)}",
        f"today  {inr(snap.daily_pnl_inr)}   (IST circuit {settings.max_daily_loss_pct:.2%})",
        f"last loop {snap.loop_id}  {snap.ts_utc}  {snap.notes}",
        "",
        "open positions:",
    ]
    positions = ledger.positions()
    if not positions:
        lines.append("  (none)")
    for pos in positions:
        lines.append(
            f"  {pos.market} {pos.side} qty={pos.qty} entry={pos.avg_entry} {pos.quote_ccy}"
        )

    exits = ledger.exit_fills()
    wins = sum(1 for f in exits if f.realized_pnl_inr > 0)
    losses = sum(1 for f in exits if f.realized_pnl_inr <= 0)
    fees = sum((f.fee_inr for f in ledger.fills(limit=10_000)), Decimal("0"))
    realized = sum((f.realized_pnl_inr for f in exits), Decimal("0"))
    lines += [
        "",
        f"closed trades: {len(exits)}  wins {wins}  losses {losses}  realized {inr(realized)}",
        f"fees paid (all fills, incl GST): {inr(fees)}",
        "",
        "recent fills:",
    ]
    fills = ledger.fills(limit=8)
    if not fills:
        lines.append("  (none yet — waiting for a momentum signal)")
    for fill in fills:
        lines.append(
            f"  #{fill.id} {fill.ts_utc} {fill.action:5} {fill.market} "
            f"{fill.qty} @ {fill.price} fee={inr(fill.fee_inr)} pnl={inr(fill.realized_pnl_inr)} {fill.reason[:80]}"
        )
    return "\n".join(lines)


def render_pnl(ledger: Ledger) -> str:
    exits = ledger.exit_fills()
    if not exits:
        return "No closed paper trades yet. Open `python -m paperbot status` for marks."
    lines = ["closed paper trades", "id  when                 market    pnl         fee        reason"]
    for f in exits:
        lines.append(
            f"{f.id:<3} {f.ts_utc} {f.market:<9} {inr(f.realized_pnl_inr):>12} {inr(f.fee_inr):>10} {f.reason[:60]}"
        )
    total = sum((f.realized_pnl_inr for f in exits), Decimal("0"))
    fees = sum((f.fee_inr for f in exits), Decimal("0"))
    lines.append(f"total realized {inr(total)}   exit fees {inr(fees)}")
    return "\n".join(lines)
