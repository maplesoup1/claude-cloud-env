"""CLI: python -m daytrader {backtest,paper,status,kill}"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from .config import load_config


def _setup_logging(log_dir: str | None, verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(Path(log_dir) / f"daytrader-{date.today():%Y%m%d}.log"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    ap = argparse.ArgumentParser(prog="daytrader")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    bt = sub.add_parser("backtest", help="run a backtest")
    bt.add_argument("--source", choices=["alpaca", "synthetic"], default="alpaca")
    bt.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    bt.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    bt.add_argument("--days", type=int, default=120, help="synthetic only")
    bt.add_argument("--slippage-bps", type=float, nargs="*", help="e.g. 2 4 8 for a stress test")
    bt.add_argument("--out", default="results")

    sub.add_parser("paper", help="run paper/live trading for today")
    sub.add_parser("status", help="show account, positions, open orders")
    sub.add_parser("kill", help="cancel all orders and close all positions NOW")

    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.cmd == "backtest":
        _setup_logging(None, args.verbose)
        logging.getLogger("daytrader.engine").setLevel(logging.DEBUG if args.verbose else logging.WARNING)
        from .backtest import run_backtest
        from .data import fetch_alpaca_minutes, synthetic_minutes

        if args.source == "synthetic":
            bars = synthetic_minutes(cfg.symbols, days=args.days)
        else:
            bars = fetch_alpaca_minutes(cfg.symbols, args.start, args.end, feed=cfg.live.feed)
        print(f"{len(bars):,} minute bars, {bars.symbol.nunique()} symbols")
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for slip in args.slippage_bps or [cfg.backtest.slippage_bps]:
            res = run_backtest(cfg, bars, slippage_bps=slip)
            print(f"\n=== slippage {slip} bps/side ===")
            print(json.dumps(res.stats, indent=2, default=str))
            res.trades.to_csv(out / f"trades_slip{slip:g}.csv", index=False)
            res.equity.to_csv(out / f"equity_slip{slip:g}.csv")
        print(f"\nresults written to {out}/")
        return

    _setup_logging(cfg.live.log_dir, args.verbose)
    from .live import kill_switch, run_live, status

    {"paper": run_live, "status": status, "kill": kill_switch}[args.cmd](cfg)


if __name__ == "__main__":
    main()
