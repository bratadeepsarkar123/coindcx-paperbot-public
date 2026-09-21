"""Environment / .env configuration. Real process env always wins over .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _truthy(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _dec(name: str, default: str) -> Decimal:
    return Decimal(os.environ.get(name, default).strip())


def _int(name: str, default: str) -> int:
    return int(os.environ.get(name, default).strip())


def _float(name: str, default: str) -> float:
    return float(os.environ.get(name, default).strip())


def _csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    owner: str = "Bratadeep"
    paper_bankroll_inr: Decimal = Decimal("100000")
    scan_interval_sec: int = 120
    pairs: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    kelly_cap: Decimal = Decimal("0.06")
    half_kelly: bool = True
    kelly_fraction: Decimal = Decimal("0.5")
    kelly_prior_p: Decimal = Decimal("0.52")
    kelly_prior_b: Decimal = Decimal("1.15")
    kelly_min_trades: int = 10
    max_daily_loss_pct: Decimal = Decimal("0.03")
    max_open_positions: int = 2
    fee_bps: Decimal = Decimal("20")
    fee_gst_pct: Decimal = Decimal("18")
    slippage_bps: Decimal = Decimal("1")
    allow_shorts: bool = False
    candle_interval: str = "1m"
    candle_limit: int = 60
    usdtinr_fallback: Decimal = Decimal("99.5")
    data_source: str = "live"
    ledger_path: Path = Path("data/ledger.sqlite")
    kill_file: Path = Path("data/KILL")
    log_path: Path = Path("data/paperbot.log")
    status_path: Path = Path("data/status.json")
    fixture_path: Path = Path("fixtures/synthetic_momentum.json")
    base_url: str = "https://api.coindcx.com"
    request_timeout_sec: float = 15.0
    min_request_interval_sec: float = 0.25
    use_orderbook: bool = False

    mom_lookback: int = 15
    mom_entry_ret: float = 0.0025
    mom_exit_ret: float = 0.0004
    mom_volume_mult: float = 1.2
    mom_stop_pct: float = 0.004
    mom_take_pct: float = 0.006
    mom_max_hold_bars: int = 12

    arm_live_trading: bool = False
    live_confirm: str = ""
    coindcx_api_key: str = ""
    coindcx_api_secret: str = ""
    broker: str = "paper"

    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def effective_kelly_fraction(self) -> Decimal:
        if self.half_kelly:
            return min(self.kelly_fraction, Decimal("0.5"))
        return self.kelly_fraction

    @property
    def live_gates_ok(self) -> bool:
        return (
            self.arm_live_trading
            and self.live_confirm == "I_UNDERSTAND_THIS_IS_LIVE"
            and bool(self.coindcx_api_key)
            and bool(self.coindcx_api_secret)
        )


def load_settings(env_file: Path | None = None, project_root: Path | None = None) -> Settings:
    root = project_root or Path(__file__).resolve().parent.parent
    path = env_file or (root / ".env")
    _load_env_file(path)

    half = _truthy("HALF_KELLY", "true")
    fraction = _dec("KELLY_FRACTION", "0.5" if half else "1.0")
    data_source = os.environ.get("DATA_SOURCE", "live").strip().lower()
    if data_source not in {"live", "fixture"}:
        raise ValueError(f"DATA_SOURCE must be live or fixture, got {data_source!r}")

    def _path(name: str, default: Path) -> Path:
        raw = Path(os.environ.get(name, str(default)))
        return raw if raw.is_absolute() else root / raw

    ledger = _path("LEDGER_PATH", root / "data" / "ledger.sqlite")

    return Settings(
        paper_bankroll_inr=_dec("PAPER_BANKROLL_INR", "100000"),
        scan_interval_sec=_int("SCAN_INTERVAL_SEC", "120"),
        pairs=tuple(_csv("PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT")),
        kelly_cap=_dec("KELLY_CAP", "0.06"),
        half_kelly=half,
        kelly_fraction=fraction,
        kelly_prior_p=_dec("KELLY_PRIOR_P", "0.52"),
        kelly_prior_b=_dec("KELLY_PRIOR_B", "1.15"),
        kelly_min_trades=_int("KELLY_MIN_TRADES", "10"),
        max_daily_loss_pct=_dec("MAX_DAILY_LOSS_PCT", "0.03"),
        max_open_positions=_int("MAX_OPEN_POSITIONS", "2"),
        fee_bps=_dec("FEE_BPS", "20"),
        fee_gst_pct=_dec("FEE_GST_PCT", "18"),
        slippage_bps=_dec("SLIPPAGE_BPS", "1"),
        allow_shorts=_truthy("ALLOW_SHORTS", "false"),
        candle_interval=os.environ.get("CANDLE_INTERVAL", "1m").strip(),
        candle_limit=_int("CANDLE_LIMIT", "60"),
        usdtinr_fallback=_dec("USDTINR_FALLBACK", "99.5"),
        data_source=data_source,
        ledger_path=ledger,
        kill_file=_path("KILL_FILE", root / "data" / "KILL"),
        log_path=_path("LOG_PATH", root / "data" / "paperbot.log"),
        status_path=_path("STATUS_PATH", root / "data" / "status.json"),
        fixture_path=_path("FIXTURE_PATH", root / "fixtures" / "synthetic_momentum.json"),
        base_url=os.environ.get("COINDCX_BASE_URL", "https://api.coindcx.com").rstrip("/"),
        request_timeout_sec=_float("REQUEST_TIMEOUT_SEC", "15"),
        min_request_interval_sec=_float("MIN_REQUEST_INTERVAL_SEC", "0.25"),
        use_orderbook=_truthy("USE_ORDERBOOK", "false"),
        mom_lookback=_int("MOM_LOOKBACK", "15"),
        mom_entry_ret=_float("MOM_ENTRY_RET", "0.0025"),
        mom_exit_ret=_float("MOM_EXIT_RET", "0.0004"),
        mom_volume_mult=_float("MOM_VOLUME_MULT", "1.2"),
        mom_stop_pct=_float("MOM_STOP_PCT", "0.004"),
        mom_take_pct=_float("MOM_TAKE_PCT", "0.006"),
        mom_max_hold_bars=_int("MOM_MAX_HOLD_BARS", "12"),
        arm_live_trading=_truthy("ARM_LIVE_TRADING", "false"),
        live_confirm=os.environ.get("LIVE_CONFIRM", "").strip(),
        coindcx_api_key=os.environ.get("COINDCX_API_KEY", "").strip(),
        coindcx_api_secret=os.environ.get("COINDCX_API_SECRET", "").strip(),
        broker=os.environ.get("BROKER", "paper").strip().lower(),
        project_root=root,
    )
