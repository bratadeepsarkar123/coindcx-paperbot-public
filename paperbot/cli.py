"""CLI: run / once / status / pnl / kill / unkilled / doctor."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from paperbot.broker.ledger import Ledger
from paperbot.broker.live_stub import LIVE_DISABLED_MESSAGE, assert_paper_only
from paperbot.broker.paper import PaperBroker
from paperbot.config import load_settings
from paperbot.logging_setup import setup_logging
from paperbot.loop import build_market_source, run_forever, run_once
from paperbot.market.fixtures import write_synthetic_fixture
from paperbot.reports import render_pnl, render_status
from paperbot.risk.controls import clear_kill, write_kill
from paperbot.strategy.momentum import MomentumStrategy


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paperbot",
        description="Bratadeep's CoinDCX Phase-1 PAPER trader. Never places real orders.",
    )
    p.add_argument("--env-file", type=Path, default=None, help="Path to .env (default: ./.env)")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Unattended paper loop")
    run.add_argument("--once", action="store_true", help="Single scan then exit")
    run.add_argument("--loops", type=int, default=None, help="Run N loops then exit")
    run.add_argument("--fixture", action="store_true", help="Use local fixtures instead of live CoinDCX")
    run.add_argument("--interval", type=int, default=None, help="Override SCAN_INTERVAL_SEC")

    sub.add_parser("status", help="Print ledger / positions / kill state")
    sub.add_parser("pnl", help="Closed-trade PnL table")
    sub.add_parser("kill", help="Create kill file (flatten + block entries on next loop)")
    sub.add_parser("unkilled", help="Remove kill file")
    sub.add_parser("doctor", help="Hit CoinDCX public API and print a sanity ticker")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings(env_file=args.env_file)

    if args.cmd == "run" and args.fixture:
        synth = settings.project_root / "fixtures" / "synthetic_momentum.json"
        if not synth.is_file():
            write_synthetic_fixture(synth)
        settings = replace(settings, data_source="fixture", fixture_path=synth)

    if args.cmd == "run" and args.interval is not None:
        settings = replace(settings, scan_interval_sec=args.interval)

    setup_logging(settings.log_path)

    if args.cmd == "run":
        try:
            assert_paper_only(settings)
        except Exception as exc:
            print(exc, file=sys.stderr)
            return 2
        if args.once:
            ledger = Ledger(settings.ledger_path)
            try:
                status = run_once(
                    settings=settings,
                    ledger=ledger,
                    broker=PaperBroker(ledger, settings),
                    strategy=MomentumStrategy(settings),
                    source=build_market_source(settings),
                )
            finally:
                ledger.close()
            print(json.dumps(status, indent=2))
            print()
            print(render_status(Ledger(settings.ledger_path), settings))
            return 0
        loops = 1 if args.once else args.loops
        run_forever(settings, loops=loops, sleep=not args.once)
        print(render_status(Ledger(settings.ledger_path), settings))
        return 0

    if args.cmd == "status":
        print(render_status(Ledger(settings.ledger_path), settings))
        return 0
    if args.cmd == "pnl":
        print(render_pnl(Ledger(settings.ledger_path)))
        return 0
    if args.cmd == "kill":
        write_kill(settings.kill_file)
        print(f"kill file written: {settings.kill_file}")
        return 0
    if args.cmd == "unkilled":
        clear_kill(settings.kill_file)
        print("kill file cleared")
        return 0
    if args.cmd == "doctor":
        print(LIVE_DISABLED_MESSAGE)
        print()
        source = build_market_source(settings)
        tickers = source.get_tickers()
        for m in list(settings.pairs) + ["USDTINR"]:
            t = tickers.get(m)
            if t is None:
                print(f"{m}: missing from ticker")
                continue
            print(f"{m}: last={t.last_price} bid={t.bid} ask={t.ask} vol={t.volume}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
