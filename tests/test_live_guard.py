from __future__ import annotations

from paperbot.broker.live_stub import LiveBroker, LiveTradingDisabledError, assert_paper_only
from paperbot.config import Settings


def test_live_broker_cannot_be_constructed() -> None:
    try:
        LiveBroker(Settings(arm_live_trading=True, live_confirm="I_UNDERSTAND_THIS_IS_LIVE",
                            coindcx_api_key="x", coindcx_api_secret="y"))
        raise AssertionError("LiveBroker must not construct")
    except LiveTradingDisabledError:
        pass


def test_assert_paper_only_blocks_armed_env() -> None:
    try:
        assert_paper_only(Settings(arm_live_trading=True))
        raise AssertionError("should refuse")
    except LiveTradingDisabledError:
        pass


def test_assert_paper_only_blocks_keys() -> None:
    try:
        assert_paper_only(Settings(coindcx_api_key="abc"))
        raise AssertionError("should refuse")
    except LiveTradingDisabledError:
        pass


def test_assert_paper_only_allows_clean_paper() -> None:
    assert_paper_only(Settings(broker="paper"))
