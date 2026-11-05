"""Configuration: one YAML file per running strategy instance; secrets from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import time
from pathlib import Path

import yaml


def parse_time(s: str | time) -> time:
    if isinstance(s, time):
        return s
    h, m = str(s).split(":")
    return time(int(h), int(m))


@dataclass
class StrategyConfig:
    name: str = "orb"
    params: dict = field(default_factory=dict)  # validated by the strategy's Params dataclass


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.005    # fraction of equity lost if stop is hit
    max_position_pct: float = 0.25   # max notional per position as fraction of equity
    max_positions: int = 3           # concurrent positions + pending entries
    daily_max_loss: float = 0.02     # halt + flatten when down this much on the day
    flatten_at: time = time(15, 45)  # flatten everything at/after this time
    min_stop_pct: float = 0.001      # reject signals whose stop is closer than this (sizing blow-up guard)


@dataclass
class BacktestConfig:
    start_equity: float = 30_000.0
    slippage_bps: float = 2.0        # per side, applied to market fills (entries, stops, flattens)
    fee_per_share: float = 0.0
    sec_fee_rate: float = 0.0000278  # on sell notional; check the current SEC rate
    feed: str = "sip"                # historical SIP (>15 min old) is free on Alpaca Basic


@dataclass
class LiveConfig:
    paper: bool = True
    feed: str = "iex"                # "iex" (free) or "sip" (paid)
    log_dir: str = "logs"


@dataclass
class Config:
    name: str = "orb"                 # instance name: prefixes order ids and log files; unique per run
    account_env: str = "ALPACA"       # reads {account_env}_API_KEY / {account_env}_SECRET_KEY
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    bar_minutes: int = 5
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    live: LiveConfig = field(default_factory=LiveConfig)


def build_dataclass(cls, data: dict | None):
    """Instantiate `cls` from a dict, rejecting unknown keys and parsing "HH:MM" into time
    for fields whose default is a `time`."""
    data = dict(data or {})
    fmap = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(fmap)
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} keys: {sorted(unknown)}")
    for k, v in data.items():
        if isinstance(fmap[k].default, time):
            data[k] = parse_time(v)
    return cls(**data)


def load_config(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    known = {f.name for f in fields(Config)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    s = raw.get("strategy") or {}
    cfg = Config(
        name=str(raw.get("name", s.get("name", "orb"))),
        account_env=str(raw.get("account_env", "ALPACA")),
        symbols=[x.upper() for x in raw.get("symbols", ["SPY", "QQQ"])],
        bar_minutes=int(raw.get("bar_minutes", 5)),
        strategy=StrategyConfig(name=s.get("name", "orb"), params=s.get("params") or {}),
        risk=build_dataclass(RiskConfig, raw.get("risk")),
        backtest=build_dataclass(BacktestConfig, raw.get("backtest")),
        live=build_dataclass(LiveConfig, raw.get("live")),
    )
    if 60 % cfg.bar_minutes:
        raise ValueError("bar_minutes must divide 60")
    if not cfg.name.replace("_", "").replace("-", "").isalnum():
        raise ValueError("name must be alphanumeric (plus - and _)")
    return cfg


def alpaca_keys(account_env: str = "ALPACA") -> tuple[str, str]:
    """Read Alpaca keys from the environment (optionally loaded from .env)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    k, s = f"{account_env}_API_KEY", f"{account_env}_SECRET_KEY"
    key, secret = os.getenv(k), os.getenv(s)
    if not key or not secret:
        raise SystemExit(f"Set {k} and {s} (see .env.example)")
    return key, secret
