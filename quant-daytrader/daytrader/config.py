"""Configuration: YAML file for strategy/risk parameters, environment for secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import time
from pathlib import Path

import yaml


def _t(s: str | time) -> time:
    if isinstance(s, time):
        return s
    h, m = str(s).split(":")
    return time(int(h), int(m))


@dataclass
class StrategyConfig:
    name: str = "orb"
    range_minutes: int = 15          # opening range = 9:30 -> 9:30+range_minutes
    volume_mult: float = 1.5         # breakout bar volume >= mult * avg volume
    volume_lookback: int = 20        # bars used for the volume average (spans days)
    reward_risk: float = 2.0         # take profit at R multiple
    stop_mode: str = "range"         # "range" = other side of range, "mid" = range midpoint
    max_stop_pct: float = 0.02       # skip if stop distance > this fraction of price
    last_entry: time = time(11, 30)  # no new entries after this time
    allow_short: bool = True
    max_trades_per_symbol: int = 1   # per day


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.005    # fraction of equity lost if stop is hit
    max_position_pct: float = 0.25   # max notional per position as fraction of equity
    max_positions: int = 3           # concurrent positions + pending entries
    daily_max_loss: float = 0.02     # halt + flatten when down this much on the day
    flatten_at: time = time(15, 45)  # flatten everything at/after this time


@dataclass
class BacktestConfig:
    start_equity: float = 30_000.0
    slippage_bps: float = 2.0        # per side, applied to market fills (entries, stops, flattens)
    fee_per_share: float = 0.0
    sec_fee_rate: float = 0.0000278  # on sell notional; check the current SEC rate


@dataclass
class LiveConfig:
    paper: bool = True
    feed: str = "iex"                # "iex" (free) or "sip" (paid)
    log_dir: str = "logs"


@dataclass
class Config:
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    bar_minutes: int = 5
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    live: LiveConfig = field(default_factory=LiveConfig)


_TIME_FIELDS = {"last_entry", "flatten_at"}


def _build(cls, data: dict | None):
    data = data or {}
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} keys: {sorted(unknown)}")
    kwargs = {k: (_t(v) if k in _TIME_FIELDS else v) for k, v in data.items()}
    return cls(**kwargs)


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    cfg = Config(
        symbols=[s.upper() for s in raw.get("symbols", ["SPY", "QQQ"])],
        bar_minutes=int(raw.get("bar_minutes", 5)),
        strategy=_build(StrategyConfig, raw.get("strategy")),
        risk=_build(RiskConfig, raw.get("risk")),
        backtest=_build(BacktestConfig, raw.get("backtest")),
        live=_build(LiveConfig, raw.get("live")),
    )
    if 60 % cfg.bar_minutes:
        raise ValueError("bar_minutes must divide 60")
    return cfg


def alpaca_keys() -> tuple[str, str]:
    """Read Alpaca keys from the environment (optionally loaded from .env)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("Set ALPACA_API_KEY and ALPACA_SECRET_KEY (see .env.example)")
    return key, secret
