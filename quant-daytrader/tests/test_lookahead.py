"""Generic look-ahead / sanity checks, run for EVERY config in configs/*.yaml.
New strategies get these for free by shipping a config."""
import logging
import statistics as st
from pathlib import Path

import pandas as pd
import pytest

from daytrader.backtest import run_backtest
from daytrader.config import load_config
from daytrader.data import synthetic_minutes

CONFIGS = sorted(Path(__file__).parent.parent.joinpath("configs").glob("*.yaml"))


@pytest.fixture(autouse=True)
def quiet():
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_truncation_does_not_change_past_decisions(path):
    """Cut the data at several points: every decision before the cut must be identical
    to the full run. Any difference means a decision used data from after its time."""
    cfg = load_config(path)
    bars = synthetic_minutes(cfg.symbols, days=12, seed=3)
    full = run_backtest(cfg, bars)
    days = sorted(bars.ts.map(lambda t: t.date()).unique())
    for day in days[4:12:3]:
        for hh, mm in [(10, 7), (12, 33), (15, 52)]:
            cut = pd.Timestamp(day).tz_localize(bars.ts.iloc[0].tz).replace(hour=hh, minute=mm)
            part = run_backtest(cfg, bars[bars.ts < cut])

            def before(df, col):
                return df[df[col] < cut - pd.Timedelta(minutes=cfg.bar_minutes + 1)] if len(df) else df

            a = before(full.signals, "ts").reset_index(drop=True)
            b = before(part.signals, "ts").reset_index(drop=True)
            pd.testing.assert_frame_equal(a, b)
            ta = full.trades[full.trades.exit_time < cut - pd.Timedelta(minutes=1)].reset_index(drop=True) if len(full.trades) else full.trades
            tb = part.trades[part.trades.exit_time < cut - pd.Timedelta(minutes=1)].reset_index(drop=True) if len(part.trades) else part.trades
            pd.testing.assert_frame_equal(ta, tb)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_no_edge_on_random_walk(path):
    """On driftless random walks no strategy should make money; a clearly positive
    average R (t > 2.5) points to look-ahead or an over-optimistic fill model."""
    cfg = load_config(path)
    rs = []
    for seed in range(3):
        res = run_backtest(cfg, synthetic_minutes(cfg.symbols, days=60, seed=100 + seed, trend=0.0))
        assert res.stats["open_positions_at_end"] == 0
        if len(res.trades):
            rs.extend(res.trades.r.dropna())
            same_day = res.trades.entry_time.map(lambda x: x.date()) == res.trades.exit_time.map(lambda x: x.date())
            assert same_day.all(), "position held overnight"
    assert len(rs) >= 30, f"too few trades to test ({len(rs)})"
    t = st.mean(rs) / (st.stdev(rs) / len(rs) ** 0.5)
    assert t < 2.5, f"suspicious edge on random data: mean R {st.mean(rs):.3f}, t={t:.2f}, n={len(rs)}"
