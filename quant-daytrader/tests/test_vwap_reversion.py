from datetime import timedelta

import pytest

from conftest import D, FakeCtx, at, mk
from daytrader.config import StrategyConfig
from daytrader.models import Exit, Position, Side
from daytrader.strategy import build_strategy

PREV = D - timedelta(days=3)  # previous Friday


def strat(**kw):
    params = {"rsi_period": 3, "market_symbol": "", "min_band_pct": 0.002}
    params.update(kw)
    return build_strategy(StrategyConfig("vwap_reversion", params), 5)


def drift_down(s, ctx, sym="X", start=100.0, until=(10, 30), step=0.1, flush=1.2, prev=True):
    """Prior close 100, a slow sell-off from 9:30, then a capitulation bar just before `until`.
    Returns (price, time of the next bar, actions emitted so far)."""
    if prev:
        s.on_bar(mk(15, 55, 100, 100, 100, 100, sym=sym, day=PREV), ctx)
    px, t = start, at(9, 30)
    out = []
    last = at(*until) - timedelta(minutes=5)
    while t < last:
        o, c = px, px - step
        out += s.on_bar(mk(t.hour, t.minute, o, o + 0.02, c - 0.02, c, v=1000, sym=sym), ctx)
        px, t = c, t + timedelta(minutes=5)
    o, c = px, px - flush
    out += s.on_bar(mk(t.hour, t.minute, o, o + 0.02, c - 0.05, c, v=1000, sym=sym), ctx)
    return c, t + timedelta(minutes=5), out


def reversal(t, px, sym="X", v=1000):
    """Bar that opens at the low and closes up 0.1, still far below VWAP."""
    return mk(t.hour, t.minute, px - 0.1, px + 0.05, px - 0.2, px, v=v, sym=sym)


def test_long_signal_on_stretched_oversold_reversal(ctx):
    s = strat()
    px, t, early = drift_down(s, ctx)
    assert early == []
    [sig] = s.on_bar(reversal(t, px), ctx)
    assert sig.side is Side.LONG
    assert sig.stop < sig.entry_ref < sig.target
    assert sig.stop <= px - 0.2                          # at least beyond the bar low
    assert sig.target == pytest.approx(s._sess["X"].vwap)


def test_requires_reversal_bar(ctx):
    s = strat()
    px, t, _ = drift_down(s, ctx)
    assert s.on_bar(mk(t.hour, t.minute, px, px + 0.02, px - 0.4, px - 0.3), ctx) == []


def test_trend_day_filter_blocks(ctx):
    s = strat(max_day_move_pct=0.02)
    px, t, _ = drift_down(s, ctx)                         # ~ -2.3% vs prior close
    assert s.on_bar(reversal(t, px), ctx) == []
    s2 = strat(max_day_move_pct=0.025)
    px, t, _ = drift_down(s2, ctx)
    assert s2.on_bar(reversal(t, px), ctx)               # same setup passes with a looser filter


def test_market_filter_uses_only_completed_market_bars(ctx):
    s = strat(market_symbol="SPY", market_max_move=0.005)
    s.on_bar(mk(15, 55, 100, 100, 100, 100, sym="SPY", day=PREV), ctx)
    s.on_bar(mk(15, 55, 100, 100, 100, 100, sym="X", day=PREV), ctx)
    t = at(9, 30)
    while t < at(10, 30):
        s.on_bar(mk(t.hour, t.minute, 100, 100, 99, 99, sym="SPY"), ctx)   # SPY -1%
        t += timedelta(minutes=5)
    px, t, _ = drift_down(s, ctx, prev=False)
    assert s.on_bar(reversal(t, px), ctx) == []


def test_market_filter_ignores_same_time_market_bar(ctx):
    """A market bar with the SAME start time as the signal bar has not completed
    before the signal bar did - it must not be used (arrival order independence)."""
    s = strat(market_symbol="SPY", market_max_move=0.005)
    px, t, _ = drift_down(s, ctx)
    s.on_bar(mk(15, 55, 100, 100, 100, 100, sym="SPY", day=PREV), ctx)
    s.on_bar(mk(t.hour, t.minute, 100, 100, 98, 98, sym="SPY"), ctx)    # same start time as signal bar
    assert s.on_bar(reversal(t, px), ctx)


def test_time_window_and_max_trades(ctx):
    s = strat(last_entry="10:00")
    px, t, _ = drift_down(s, ctx)
    assert s.on_bar(reversal(t, px), ctx) == []
    s2 = strat()
    s2.on_bar(mk(15, 55, 100, 100, 100, 100, day=PREV), ctx)
    s2.mark_traded("X", D.date())                         # live: called after warm-up
    px, t, _ = drift_down(s2, ctx, prev=False)
    assert s2.on_bar(reversal(t, px), ctx) == []


def test_short_mirror(ctx):
    s = strat()
    s.on_bar(mk(15, 55, 100, 100, 100, 100, day=PREV), ctx)
    px, t = 100.0, at(9, 30)
    while t < at(10, 25):
        o, c = px, px + 0.1
        s.on_bar(mk(t.hour, t.minute, o, c + 0.02, o - 0.02, c), ctx)
        px, t = c, t + timedelta(minutes=5)
    s.on_bar(mk(t.hour, t.minute, px, px + 1.25, px - 0.02, px + 1.2), ctx)
    px, t = px + 1.2, t + timedelta(minutes=5)
    [sig] = s.on_bar(mk(t.hour, t.minute, px + 0.1, px + 0.2, px - 0.05, px), ctx)
    assert sig.side is Side.SHORT and sig.target < sig.entry_ref < sig.stop


def test_time_stop_exit():
    s = strat(max_hold_minutes=30)
    ctx = FakeCtx()
    px, t, _ = drift_down(s, ctx)
    assert s.on_bar(reversal(t, px), ctx)
    held = FakeCtx({"X": Position("X", Side.LONG, 1, px)})
    acts = []
    for i in range(1, 7):
        tt = t + timedelta(minutes=5 * i)
        acts += s.on_bar(mk(tt.hour, tt.minute, px, px, px, px), held)
    exits = [a for a in acts if isinstance(a, Exit)]
    assert len(exits) == 1 and exits[0].reason == "time_stop"
    assert exits[0].ts == t + timedelta(minutes=30)       # bar ending 30 min after the signal bar ended


def test_no_new_signal_while_in_position_and_time_stop_not_extended():
    """Review finding: a second signal during an open trade must not reset the time stop
    or consume the day's trade quota."""
    def run(ctx_after_entry):
        s = strat(max_hold_minutes=60, cooldown_minutes=0, max_day_move_pct=0.5)
        px, t, _ = drift_down(s, FakeCtx())
        assert s.on_bar(reversal(t, px), FakeCtx())        # entry, signal bar ends t+5
        acts, p2 = [], px
        for i in range(1, 14):
            tt = t + timedelta(minutes=5 * i)
            if i == 7:                                     # a valid 2nd signal if flat
                acts += s.on_bar(reversal(tt, p2), ctx_after_entry)
                continue
            o, c = p2, p2 - 1.0                            # deep second flush
            acts += s.on_bar(mk(tt.hour, tt.minute, o, o + 0.02, c - 0.05, c), ctx_after_entry)
            p2 = c
        return s, t, acts

    # control: with no position the setup DOES produce a second signal
    _, _, flat_acts = run(FakeCtx())
    assert any(not isinstance(a, Exit) for a in flat_acts)

    s, t, acts = run(FakeCtx({"X": Position("X", Side.LONG, 1, 95)}))
    exits = [a for a in acts if isinstance(a, Exit)]
    signals = [a for a in acts if not isinstance(a, Exit)]
    assert signals == []
    assert len(exits) == 1 and exits[0].ts == t + timedelta(minutes=60)
    assert s._days["X"].trades == 1


def test_restart_with_unknown_position_starts_time_stop_clock():
    s = strat(max_hold_minutes=30)
    held = FakeCtx({"X": Position("X", Side.LONG, 1, 100)})
    acts = []
    for i in range(8):
        tt = at(11, 0) + timedelta(minutes=5 * i)
        acts += s.on_bar(mk(tt.hour, tt.minute, 100, 100, 100, 100), held)
    exits = [a for a in acts if isinstance(a, Exit)]
    assert len(exits) == 1 and exits[0].ts == at(11, 30)
