"""Live CoinDCX order path — present as a stub, impossible to fire in Phase-1.

Even if ARM_LIVE_TRADING, LIVE_CONFIRM, and API keys are all set, this module
never sends HTTP to /exchange/v1/orders/*. Phase-1 is paper-only.
"""

from __future__ import annotations

from paperbot.config import Settings


class LiveTradingDisabledError(RuntimeError):
    pass


LIVE_DISABLED_MESSAGE = (
    "LIVE TRADING IS DISABLED. This is a Phase-1 PAPER bot. "
    "CoinDCX private order endpoints are not implemented and will not be called. "
    "To even consider a future live path you would need ALL of: "
    "BROKER=live, ARM_LIVE_TRADING=true, LIVE_CONFIRM=I_UNDERSTAND_THIS_IS_LIVE, "
    "COINDCX_API_KEY, COINDCX_API_SECRET, and a Phase-2 implementation. "
    "Keys are not required and must not be set for Phase-1."
)


class LiveBroker:
    name = "live"

    def __init__(self, settings: Settings) -> None:
        del settings
        raise LiveTradingDisabledError(LIVE_DISABLED_MESSAGE)

    def place_order(self, *args: object, **kwargs: object) -> None:
        raise LiveTradingDisabledError(LIVE_DISABLED_MESSAGE)


def assert_paper_only(settings: Settings) -> None:
    if settings.broker not in {"paper", ""}:
        raise LiveTradingDisabledError(LIVE_DISABLED_MESSAGE)
    if settings.arm_live_trading or settings.live_confirm or settings.coindcx_api_key or settings.coindcx_api_secret:
        raise LiveTradingDisabledError(
            "Refusing to start: live-trading related env is set. "
            "Unset ARM_LIVE_TRADING, LIVE_CONFIRM, COINDCX_API_KEY, COINDCX_API_SECRET. "
            + LIVE_DISABLED_MESSAGE
        )
