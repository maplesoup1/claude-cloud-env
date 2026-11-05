from datetime import timedelta

import pytest

from conftest import D, FakeCtx, at, mk
from daytrader.config import StrategyConfig
from daytrader.models import Side
from daytrader.strategy import build_strategy

PREV = D - timedelta(days=3)


def strat(**kw):
    return build_strategy(StrategyConfig("gap_fade", kw), 5)


def gap_up_open(s, ctx, open_px=102.0, prev_close=100.0):
    """Prior close 100, gap up 2%, opening range 9:30-9:45 = [101.5, 102.6]."""
    s.on_bar(mk(15, 55, prev_close, prev_close, prev_close, prev_close, day=PREV), ctx)
    assert s.on_bar(mk(9, 30, open_px, 102.6, 101.8, 102.3), ctx) == []
    assert s.on_bar(mk(9, 35, 102.3, 102.5, 101.5, 101.7), ctx) == []
    assert s.on_bar(mk(9, 40, 101.7, 102.0, 101.6, 101.9), ctx) == []


def test_short_after_failed_gap_up(ctx):
    s = strat()
    gap_up_open(s, ctx)
    [sig] = s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx)   # closes below OR low 101.5 and VWAP
    assert sig.side is Side.SHORT
    assert sig.target == pytest.approx(102 - 0.75 * 2)                # 100.5
    assert sig.stop == pytest.approx(s._sess["X"].vwap * 1.002)
    assert sig.stop > s._sess["X"].vwap > sig.entry_ref
    assert s.on_bar(mk(9, 50, 101.3, 101.4, 101.0, 101.1), ctx) == []  # one per day


def test_session_high_stop_mode(ctx):
    s = strat(stop_mode="session_high", min_rr=0.5)
    gap_up_open(s, ctx)
    [sig] = s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx)
    assert sig.stop == pytest.approx(102.6 * 1.002)
    s2 = strat(stop_mode="session_high")                             # rr 0.63 < 1.0 -> skipped
    gap_up_open(s2, ctx)
    assert s2.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []


def test_no_signal_inside_range_or_above_vwap(ctx):
    s = strat()
    gap_up_open(s, ctx)
    assert s.on_bar(mk(9, 45, 101.8, 101.9, 101.55, 101.6), ctx) == []  # above OR low


def test_gap_size_filters(ctx):
    s = strat(min_gap=0.03)
    gap_up_open(s, ctx)
    assert s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []
    s2 = strat(max_gap=0.015)
    gap_up_open(s2, ctx)
    assert s2.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []


def test_already_filled_gap_is_skipped(ctx):
    s = strat(fill_frac=0.75)
    gap_up_open(s, ctx)
    s.on_bar(mk(9, 45, 101.6, 101.7, 100.4, 101.6), ctx)             # traded through the 100.5 target
    assert s.on_bar(mk(9, 50, 101.6, 101.6, 101.3, 101.35), ctx) == []


def test_long_after_failed_gap_down(ctx):
    s = strat()
    s.on_bar(mk(15, 55, 100, 100, 100, 100, day=PREV), ctx)
    s.on_bar(mk(9, 30, 98.0, 98.2, 97.4, 97.7), ctx)
    s.on_bar(mk(9, 35, 97.7, 98.5, 97.5, 98.3), ctx)
    s.on_bar(mk(9, 40, 98.3, 98.4, 98.0, 98.1), ctx)
    [sig] = s.on_bar(mk(9, 45, 98.2, 98.8, 98.2, 98.7), ctx)
    assert sig.side is Side.LONG and sig.stop < sig.entry_ref < sig.target
    assert sig.target == pytest.approx(98 + 0.75 * 2)


def test_missed_open_means_no_trade(ctx):
    """Started mid-session without the 9:30 bar: the gap cannot be trusted."""
    s = strat()
    s.on_bar(mk(15, 55, 100, 100, 100, 100, day=PREV), ctx)
    s.on_bar(mk(9, 35, 102.3, 102.5, 101.5, 101.7), ctx)
    s.on_bar(mk(9, 40, 101.7, 102.0, 101.6, 101.9), ctx)
    assert s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []


def test_stop_too_wide_or_bad_rr(ctx):
    s = strat(max_stop_pct=0.005)
    gap_up_open(s, ctx)
    assert s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []
    s2 = strat(min_rr=3)
    gap_up_open(s2, ctx)
    assert s2.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []


# ---- review findings --------------------------------------------------------
def test_missing_930_minute_is_detected():
    """The aggregated 5m bar starts at 9:30 even if the 9:30 minute was missing;
    bar.first exposes the first minute actually seen."""
    from daytrader.models import Bar
    s = strat()
    ctx = FakeCtx()
    s.on_bar(mk(15, 55, 100, 100, 100, 100, day=PREV), ctx)
    s.on_bar(Bar("X", at(9, 30), 102, 102.6, 101.8, 102.3, 1000, first_ts=at(9, 31)), ctx)
    s.on_bar(mk(9, 35, 102.3, 102.5, 101.5, 101.7), ctx)
    s.on_bar(mk(9, 40, 101.7, 102.0, 101.6, 101.9), ctx)
    assert s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []


def test_stale_prior_close_is_rejected(ctx):
    s = strat()
    s.on_bar(mk(15, 55, 100, 100, 100, 100, day=D - timedelta(days=8)), ctx)  # a week+ old
    s.on_bar(mk(9, 30, 102.0, 102.6, 101.8, 102.3), ctx)
    s.on_bar(mk(9, 35, 102.3, 102.5, 101.5, 101.7), ctx)
    s.on_bar(mk(9, 40, 101.7, 102.0, 101.6, 101.9), ctx)
    assert s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx) == []
    s2 = strat()                                                         # control: last Friday is fine
    gap_up_open(s2, ctx)
    assert s2.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx)


def test_stop_at_least_min_atr_away(ctx):
    s = strat(atr_period=2, min_stop_atr=1.0, min_rr=0.1, max_stop_pct=0.05)
    gap_up_open(s, ctx)
    [sig] = s.on_bar(mk(9, 45, 101.8, 101.9, 101.3, 101.35), ctx)
    atr = s._atr["X"].value
    assert sig.stop - sig.entry_ref >= atr - 1e-9
    assert sig.stop >= s._sess["X"].vwap * 1.002 - 1e-9
