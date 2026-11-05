import pytest

from conftest import D, FakeCtx, mk
from daytrader.config import StrategyConfig
from daytrader.models import Exit, Position, Side
from daytrader.strategy import build_strategy


def orb(**kw):
    params = {"volume_lookback": 2, "vwap_filter": False, "max_range_pct": 0.05}
    params.update(kw)
    return build_strategy(StrategyConfig("orb", params), 5)


def feed_range(s, ctx):
    for m in (30, 35, 40):
        assert s.on_bar(mk(9, m, 100, 101, 99, 100, v=1000), ctx) == []


def test_long_breakout(ctx):
    s = orb()
    feed_range(s, ctx)
    [sig] = s.on_bar(mk(9, 45, 100.5, 101.5, 100.4, 101.2, v=2000), ctx)
    assert sig.side is Side.LONG and sig.stop == 99
    assert sig.target == pytest.approx(101.2 + 2 * (101.2 - 99))
    assert s.on_bar(mk(9, 50, 101, 102, 101, 101.8, v=5000), ctx) == []  # one per day


def test_volume_and_last_entry(ctx):
    s = orb()
    feed_range(s, ctx)
    assert s.on_bar(mk(9, 45, 100.5, 101.5, 100.4, 101.2, v=1000), ctx) == []
    s2 = orb()
    feed_range(s2, ctx)
    assert s2.on_bar(mk(11, 30, 100.5, 101.5, 100.4, 101.2, v=9000), ctx) == []


def test_short_and_no_short(ctx):
    s = orb()
    feed_range(s, ctx)
    [sig] = s.on_bar(mk(9, 45, 99.5, 99.6, 98.5, 98.8, v=2000), ctx)
    assert sig.side is Side.SHORT and sig.stop == 101
    s2 = orb(allow_short=False)
    feed_range(s2, ctx)
    assert s2.on_bar(mk(9, 45, 99.5, 99.6, 98.5, 98.8, v=2000), ctx) == []


def test_range_width_filter(ctx):
    s = orb(max_range_pct=0.01)  # range is 2%
    feed_range(s, ctx)
    assert s.on_bar(mk(9, 45, 100.5, 101.5, 100.4, 101.2, v=2000), ctx) == []


def test_vwap_filter_blocks_long_below_vwap(ctx):
    s = orb(vwap_filter=True)
    feed_range(s, ctx)
    # closes above the range high (101) but spiked to 102 and faded: its heavy volume
    # puts VWAP at ~101.3, above the close -> long blocked
    assert s.on_bar(mk(9, 45, 101.9, 102, 101, 101.05, v=10**6), ctx) == []
    s2 = orb(vwap_filter=True)
    feed_range(s2, ctx)
    [sig] = s2.on_bar(mk(9, 45, 100.5, 101.5, 100.4, 101.2, v=2000), ctx)
    assert sig.side is Side.LONG


def test_mark_traded(ctx):
    s = orb()
    s.mark_traded("X", D.date())
    feed_range(s, ctx)
    assert s.on_bar(mk(9, 45, 100.5, 101.5, 100.4, 101.2, v=2000), ctx) == []


def test_time_stop():
    s = orb(max_hold_minutes=30)
    ctx = FakeCtx()
    feed_range(s, ctx)
    assert s.on_bar(mk(9, 45, 100.5, 101.5, 100.4, 101.2, v=2000), ctx)
    held = FakeCtx({"X": Position("X", Side.LONG, 1, 101.2)})
    assert s.on_bar(mk(10, 10, 101, 101, 101, 101), held) == []
    [ex] = s.on_bar(mk(10, 15, 101, 101, 101, 101), held)  # bar ends 10:20 = 30 min after 9:50
    assert isinstance(ex, Exit) and ex.reason == "time_stop"
