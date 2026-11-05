"""CLI: python -m daytrader [-c cfg.yaml ...] {backtest,paper,status,kill,list}"""
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
    ap.add_argument("-c", "--config", action="append",
                    help="strategy instance config; repeat to run several (default: configs/orb.yaml)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    bt = sub.add_parser("backtest", help="backtest each config (and the combination)")
    bt.add_argument("--source", choices=["alpaca", "synthetic"], default="alpaca")
    bt.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    bt.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    bt.add_argument("--days", type=int, default=120, help="synthetic only")
    bt.add_argument("--seed", type=int, default=7, help="synthetic only")
    bt.add_argument("--slippage-bps", type=float, nargs="*", help="e.g. 2 4 8 for a stress test")
    bt.add_argument("--out", default="results")

    sub.add_parser("paper", help="trade today (paper unless live.paper=false)")
    sub.add_parser("status", help="show accounts, positions, open orders")
    sub.add_parser("kill", help="cancel ALL orders and close ALL positions in each account NOW")
    sub.add_parser("list", help="list available strategies and their parameters")

    args = ap.parse_args()
    if args.cmd == "list":
        from dataclasses import fields

        from .strategy import REGISTRY
        for name, cls in sorted(REGISTRY.items()):
            print(f"{name}: {(cls.__doc__ or cls.__module__).strip().splitlines()[0]}")
            for f in fields(cls.Params):
                print(f"    {f.name} = {f.default!r}")
        return

    cfgs = [load_config(p) for p in (args.config or ["configs/orb.yaml"])]

    if args.cmd == "backtest":
        _setup_logging(None, args.verbose)
        logging.getLogger("daytrader.engine").setLevel(logging.DEBUG if args.verbose else logging.WARNING)
        from .backtest import portfolio_report, run_backtest
        from .data import fetch_alpaca_minutes, synthetic_minutes

        symbols = sorted({s for c in cfgs for s in c.symbols})
        if args.source == "synthetic":
            bars = synthetic_minutes(symbols, days=args.days, seed=args.seed)
        else:
            bars = fetch_alpaca_minutes(symbols, args.start, args.end, feed=cfgs[0].backtest.feed,
                                        account_env=cfgs[0].account_env)
        print(f"{len(bars):,} minute bars, {bars.symbol.nunique()} symbols")
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for slip in args.slippage_bps or [None]:
            results = [run_backtest(c, bars, slippage_bps=slip) for c in cfgs]
            label = "config" if slip is None else f"{slip:g}"
            for c, res in zip(cfgs, results):
                print(f"\n=== {c.name} ({c.strategy.name}) slippage={label} bps/side ===")
                print(json.dumps(res.stats, indent=2, default=str))
                res.trades.to_csv(out / f"{c.name}_trades_slip{label}.csv", index=False)
                res.equity.to_csv(out / f"{c.name}_equity_slip{label}.csv")
            if len(cfgs) > 1:
                print(f"\n=== combined ({len(cfgs)} accounts) slippage={label} ===")
                print(json.dumps(portfolio_report(results, [c.backtest.start_equity for c in cfgs]),
                                 indent=2, default=str))
        print(f"\nresults written to {out}/")
        return

    _setup_logging(cfgs[0].live.log_dir, args.verbose)
    from .live import kill_switch, run_live, status

    {"paper": run_live, "status": status, "kill": kill_switch}[args.cmd](cfgs)


if __name__ == "__main__":
    main()
