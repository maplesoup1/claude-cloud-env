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
    name: str
    trades: pd.DataFrame
    equity: pd.Series
    stats: dict
    signals: pd.DataFrame


def run_backtest(cfg: Config, bars: pd.DataFrame, slippage_bps: float | None = None) -> BacktestResult:
    bt_cfg = cfg.backtest if slippage_bps is None else replace(cfg.backtest, slippage_bps=slippage_bps)
    bars = bars[bars.symbol.isin(cfg.symbols)]
    broker = SimBroker(bt_cfg)
    engine = Engine(build_strategy(cfg.strategy, cfg.bar_minutes), RiskManager(cfg.risk), broker,
                    cfg.bar_minutes, name=cfg.name)
    for bar in iter_bars(bars):
        engine.on_minute_bar(bar)
    broker.finish()

    trades = pd.DataFrame(broker.trades)
    equity = pd.Series({d: e for d, e in broker.daily_equity}, name=cfg.name, dtype=float)
    stats = compute_stats(trades, equity, bt_cfg.start_equity)
    stats["rejected_entries"] = broker.rejected
    stats["open_positions_at_end"] = len(broker.positions())
    sig = pd.DataFrame(engine.signals)
    if len(sig):
        stats["signals_rejected_by_risk"] = sig[sig.qty <= 0].decision.value_counts().to_dict()
    return BacktestResult(cfg.name, trades, equity, stats, sig)


def compute_stats(trades: pd.DataFrame, equity: pd.Series, start_equity: float) -> dict:
    s: dict = {"trades": int(len(trades))}
    if len(equity):
        rets = equity.pct_change().fillna(equity.iloc[0] / start_equity - 1)
        peak = equity.cummax().clip(lower=start_equity)
        s["final_equity"] = round(float(equity.iloc[-1]), 2)
        s["total_return_pct"] = round(float(equity.iloc[-1] / start_equity - 1) * 100, 2)
        s["max_drawdown_pct"] = round(float(((equity / peak) - 1).min() * 100), 2)
        s["sharpe_daily_ann"] = round(float(rets.mean() / rets.std() * math.sqrt(252)), 2) if rets.std() > 0 else None
        s["worst_day_pct"] = round(float(rets.min() * 100), 2)
        s["days"] = int(len(equity))
        s["days_traded_pct"] = round(float((rets != 0).mean() * 100), 1)
    if len(trades):
        wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
        r = trades.r.dropna()
        s["win_rate_pct"] = round(len(wins) / len(trades) * 100, 1)
        s["avg_r"] = round(float(r.mean()), 3)
        s["avg_r_tstat"] = round(float(r.mean() / (r.std() / math.sqrt(len(r)))), 2) if len(r) > 2 and r.std() > 0 else None
        s["profit_factor"] = round(float(wins.pnl.sum() / -losses.pnl.sum()), 2) if losses.pnl.sum() < 0 else None
        s["long_short_pnl"] = trades.groupby("side").pnl.sum().round(2).to_dict()
        hold = (pd.to_datetime(trades.exit_time) - pd.to_datetime(trades.entry_time)).dt.total_seconds() / 60
        s["avg_hold_min"] = round(float(hold.mean()), 1)
        s["exit_reasons"] = trades.reason.value_counts().to_dict()
        s["by_entry_hour_pnl"] = trades.groupby(pd.to_datetime(trades.entry_time).map(lambda t: t.hour)).pnl.sum().round(2).to_dict()
        s["by_symbol_pnl"] = trades.groupby("symbol").pnl.sum().round(2).sort_values().to_dict()
    return s


def portfolio_report(results: list[BacktestResult], start_equities: list[float]) -> dict:
    """Combine several strategy instances (separate accounts): correlation and summed P&L."""
    eq = pd.concat([r.equity for r in results], axis=1).sort_index().ffill()
    for col, start in zip(eq.columns, start_equities):
        eq[col] = eq[col].fillna(start)
    pnl = eq - pd.Series(start_equities, index=eq.columns)
    total_start = sum(start_equities)
    total = pnl.sum(axis=1) + total_start
    rets = eq.pct_change().fillna(0)
    out = compute_stats(pd.DataFrame(), total, total_start)
    out["daily_return_correlation"] = rets.corr().round(2).to_dict() if len(results) > 1 else None
    return out
