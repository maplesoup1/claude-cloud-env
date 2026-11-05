"""Run the live engine over historical minute bars with a SimBroker."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import pandas as pd

from .broker.sim import SimBroker
from .config import Config
from .data import iter_bars
from .engine import Engine
from .risk import RiskManager
from .strategy import build_strategy


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    stats: dict
    signals: pd.DataFrame


def run_backtest(cfg: Config, bars: pd.DataFrame, slippage_bps: float | None = None) -> BacktestResult:
    bt_cfg = cfg.backtest if slippage_bps is None else replace(cfg.backtest, slippage_bps=slippage_bps)
    broker = SimBroker(bt_cfg)
    engine = Engine(build_strategy(cfg.strategy, cfg.bar_minutes), RiskManager(cfg.risk), broker, cfg.bar_minutes)
    for bar in iter_bars(bars):
        engine.on_minute_bar(bar)
    broker.finish()

    trades = pd.DataFrame(broker.trades)
    equity = pd.Series({d: e for d, e in broker.daily_equity}, name="equity", dtype=float)
    stats = compute_stats(trades, equity, bt_cfg.start_equity)
    stats["rejected_entries"] = broker.rejected
    stats["open_positions_at_end"] = len(broker.positions())
    return BacktestResult(trades, equity, stats, pd.DataFrame(engine.signals))


def compute_stats(trades: pd.DataFrame, equity: pd.Series, start_equity: float) -> dict:
    s: dict = {"trades": int(len(trades))}
    if len(equity):
        rets = equity.pct_change().fillna(equity.iloc[0] / start_equity - 1)
        peak = equity.cummax()
        s["final_equity"] = round(float(equity.iloc[-1]), 2)
        s["total_return_pct"] = round((equity.iloc[-1] / start_equity - 1) * 100, 2)
        s["max_drawdown_pct"] = round(float(((equity / peak) - 1).min() * 100), 2)
        s["sharpe_daily_ann"] = round(float(rets.mean() / rets.std() * math.sqrt(252)), 2) if rets.std() > 0 else None
        s["worst_day_pct"] = round(float(rets.min() * 100), 2)
        s["days"] = int(len(equity))
    if len(trades):
        wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
        s["win_rate_pct"] = round(len(wins) / len(trades) * 100, 1)
        s["avg_r"] = round(float(trades.r.dropna().mean()), 3)
        s["profit_factor"] = round(float(wins.pnl.sum() / -losses.pnl.sum()), 2) if losses.pnl.sum() < 0 else None
        s["exit_reasons"] = trades.reason.value_counts().to_dict()
        s["by_entry_hour_pnl"] = trades.groupby(pd.to_datetime(trades.entry_time).map(lambda t: t.hour)).pnl.sum().round(2).to_dict()
    return s
