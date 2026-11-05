from datetime import datetime

import pytest

from daytrader.broker.sim import SimBroker
from daytrader.config import BacktestConfig
from daytrader.models import NY, Bar

D = datetime(2025, 3, 3, tzinfo=NY)  # a Monday


def at(h, m, day=D):
    return day.replace(hour=h, minute=m)


def mk(h, m, o, hi, lo, c, v=1000, sym="X", day=D):
    return Bar(sym, at(h, m, day), o, hi, lo, c, v)


def flat(h, m, px, v=1000, sym="X", day=D):
    return mk(h, m, px, px, px, px, v, sym, day)


def sim_broker(slip=0.0, equity=10_000):
    return SimBroker(BacktestConfig(start_equity=equity, slippage_bps=slip, sec_fee_rate=0))


class FakeCtx:
    """Strategy context for unit tests."""

    def __init__(self, positions=None, now=None):
        self.positions = positions or {}
        self.now = now

    def position(self, symbol):
        return self.positions.get(symbol)


@pytest.fixture
def ctx():
    return FakeCtx()
