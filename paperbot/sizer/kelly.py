"""Kelly position sizing with hard cap and optional half-Kelly."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN

MONEY = Decimal("0.00000001")
INR = Decimal("0.01")


def _q(value: Decimal, quant: Decimal = MONEY) -> Decimal:
    return value.quantize(quant, rounding=ROUND_HALF_EVEN)


def kelly_fraction(
    *,
    p: Decimal,
    b: Decimal,
    fraction: Decimal,
    cap: Decimal,
) -> Decimal:
    """f* = p - (1-p)/b for a bet that pays b:1 with win probability p.

    Returns a bankroll fraction in [0, cap]. Negative or undefined edge → 0.
    """
    if p <= 0 or p >= 1:
        return Decimal("0")
    if b <= 0:
        return Decimal("0")
    q = Decimal("1") - p
    full = p - (q / b)
    if full <= 0:
        return Decimal("0")
    sized = full * fraction
    if sized <= 0:
        return Decimal("0")
    if cap <= 0:
        return Decimal("0")
    return min(sized, cap)


@dataclass(frozen=True)
class TradeSample:
    win: bool
    pnl_inr: Decimal


def estimate_p_and_b(
    samples: list[TradeSample],
    *,
    prior_p: Decimal,
    prior_b: Decimal,
    min_trades: int,
) -> tuple[Decimal, Decimal, str]:
    """Use priors until enough closed trades exist; then Laplace-smoothed empirical."""
    if len(samples) < min_trades:
        return prior_p, prior_b, f"prior n={len(samples)}<{min_trades}"

    wins = [s for s in samples if s.win]
    losses = [s for s in samples if not s.win]
    n = len(samples)
    p = (Decimal(len(wins)) + Decimal("1")) / (Decimal(n) + Decimal("2"))
    avg_win = (
        sum((s.pnl_inr for s in wins), Decimal("0")) / Decimal(len(wins))
        if wins
        else Decimal("0")
    )
    avg_loss = (
        abs(sum((s.pnl_inr for s in losses), Decimal("0")) / Decimal(len(losses)))
        if losses
        else Decimal("0")
    )
    if avg_loss <= 0 and avg_win > 0:
        b = Decimal("10")  # all wins: cap the odds instead of inf
    elif avg_win <= 0:
        b = Decimal("0.01")  # no wins: near-zero edge
    else:
        b = avg_win / avg_loss
    return p, b, f"empirical n={n} wins={len(wins)}"


def size_notional_inr(
    *,
    equity_inr: Decimal,
    p: Decimal,
    b: Decimal,
    fraction: Decimal,
    cap: Decimal,
) -> tuple[Decimal, Decimal, str]:
    """Return (notional_inr, f_used, note). Cap is a fraction of current equity."""
    if equity_inr <= 0:
        return Decimal("0"), Decimal("0"), "no_equity"
    hard_cap = min(cap, Decimal("0.06"))  # never more than 6% even if misconfigured
    f = kelly_fraction(p=p, b=b, fraction=fraction, cap=hard_cap)
    notional = _q(equity_inr * f, INR)
    return notional, f, f"kelly f={f} p={p} b={b} cap={hard_cap}"


def qty_from_notional(notional_quote: Decimal, price: Decimal) -> Decimal:
    if price <= 0:
        return Decimal("0")
    return _q(notional_quote / price, MONEY)


def apply_slippage(price: Decimal, side: str, slippage_bps: Decimal) -> Decimal:
    bump = price * (slippage_bps / Decimal("10000"))
    if side == "buy":
        return _q(price + bump)
    return _q(max(price - bump, MONEY))


def fee_on_notional(notional: Decimal, fee_bps: Decimal, gst_pct: Decimal) -> Decimal:
    raw = notional * (fee_bps / Decimal("10000"))
    with_gst = raw * (Decimal("1") + gst_pct / Decimal("100"))
    return _q(with_gst)


def round_inr(value: Decimal) -> Decimal:
    return value.quantize(INR, rounding=ROUND_DOWN)
