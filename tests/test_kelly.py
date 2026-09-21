from __future__ import annotations

from decimal import Decimal

import pytest

from paperbot.sizer.kelly import fee_on_notional, kelly_fraction, size_notional_inr


def test_kelly_zero_when_no_edge() -> None:
    assert kelly_fraction(p=Decimal("0.40"), b=Decimal("1.0"), fraction=Decimal("1"), cap=Decimal("0.06")) == Decimal("0")
    assert kelly_fraction(p=Decimal("0.50"), b=Decimal("1.0"), fraction=Decimal("1"), cap=Decimal("0.06")) == Decimal("0")


def test_kelly_negative_odds() -> None:
    assert kelly_fraction(p=Decimal("0.60"), b=Decimal("0"), fraction=Decimal("1"), cap=Decimal("0.06")) == Decimal("0")
    assert kelly_fraction(p=Decimal("1.0"), b=Decimal("2"), fraction=Decimal("1"), cap=Decimal("0.06")) == Decimal("0")


def test_full_kelly_then_hard_cap() -> None:
    # f* = 0.55 - 0.45/1.2 = 0.175 → cap 6%
    f = kelly_fraction(p=Decimal("0.55"), b=Decimal("1.2"), fraction=Decimal("1"), cap=Decimal("0.06"))
    assert f == Decimal("0.06")


def test_half_kelly_prior_under_cap() -> None:
    # f* = 0.52 - 0.48/1.15 ≈ 0.1026087; half ≈ 0.051304
    f = kelly_fraction(p=Decimal("0.52"), b=Decimal("1.15"), fraction=Decimal("0.5"), cap=Decimal("0.06"))
    assert f == pytest.approx(Decimal("0.0513043478"), rel=Decimal("1e-6"))


def test_size_never_exceeds_six_percent_even_if_cap_misconfigured() -> None:
    notional, f, _ = size_notional_inr(
        equity_inr=Decimal("100000"),
        p=Decimal("0.70"),
        b=Decimal("2"),
        fraction=Decimal("1"),
        cap=Decimal("0.50"),
    )
    assert f == Decimal("0.06")
    assert notional == Decimal("6000.00")


def test_fee_bps_plus_gst() -> None:
    # 20 bps of 10_000 = 20; +18% GST = 23.6
    fee = fee_on_notional(Decimal("10000"), Decimal("20"), Decimal("18"))
    assert fee == Decimal("23.60000000")


def test_fee_without_gst() -> None:
    fee = fee_on_notional(Decimal("10000"), Decimal("20"), Decimal("0"))
    assert fee == Decimal("20.00000000")
