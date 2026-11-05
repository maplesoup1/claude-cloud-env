from datetime import time, timedelta

import pytest

from conftest import D, at, mk
from daytrader.config import StrategyConfig
from daytrader.models import Side
from daytrader.strategy import build_strategy

PREV = D - timedelta(days=3)


def strat(**kw):
    params = {"atr_period": 3, "vwap_confirm": False}
    params.update(kw)
    return build_strategy(StrategyConfig("intraday_momentum", params), 5)


def run_day(s, ctx, path, sym="X"):
    """path(t) -> close price for the 5m bar starting at t. Returns all actions."""
    s.on_bar(mk(15, 55, 100, 100, 100, 100, sym=sym, day=PREV), ctx)
    out = []
    t = at(9, 30)
    prev = 100.0
    while t < at(16, 0):
        c = path(t)
        out += [(t, a) for a in s.on_bar(mk(t.hour, t.minute, prev, max(prev, c) + 0.05,
                                            min(prev, c) - 0.05, c, sym=sym), ctx)]
        prev, t = c, t + timedelta(minutes=5)
    return out


def up_day(t):
    return 100 + 0.01 * ((t - at(9, 30)).seconds // 300)        # +0.72% by 15:30


def down_day(t):
    return 100 - 0.01 * ((t - at(9, 30)).seconds // 300)


def test_long_on_up_day_at_signal_time(ctx):
    [(t, sig)] = run_day(strat(), ctx, up_day)
    assert t == at(15, 25) and sig.side is Side.LONG              # bar 15:25-15:30
    assert sig.stop < sig.entry_ref < sig.target


def test_short_on_down_day_and_no_short(ctx):
    [(t, sig)] = run_day(strat(), ctx, down_day)
    assert sig.side is Side.SHORT and sig.target < sig.entry_ref < sig.stop
    assert run_day(strat(allow_short=False), ctx, down_day) == []


def test_min_and_max_move(ctx):
    assert run_day(strat(min_move=0.01), ctx, up_day) == []
    assert run_day(strat(max_move=0.005), ctx, up_day) == []


def test_mode_both_requires_agreement(ctx):
    def v_shape(t):  # down 1% at 10:00, then rallies to +0.7% by 15:30
        k = (t - at(9, 30)).seconds // 300
        return 100 - 0.2 * min(k, 5) + 0.035 * max(k - 5, 0)
    assert run_day(strat(mode="close_to_signal"), ctx, v_shape)
    assert run_day(strat(mode="both"), ctx, v_shape) == []
    [(t, sig)] = run_day(strat(mode="first_half_hour"), ctx, v_shape)
    assert sig.side is Side.SHORT


def test_no_trade_without_prior_close(ctx):
    s = strat()
    out = []
    t = at(9, 30)
    while t < at(16, 0):
        out += s.on_bar(mk(t.hour, t.minute, 100, 101, 99, up_day(t)), ctx)
        t += timedelta(minutes=5)
    assert out == []


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        build_strategy(StrategyConfig("intraday_momentum", {"mode": "nope"}), 5)
