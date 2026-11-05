"""Configuration: one YAML file per running strategy instance; secrets from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import time
from pathlib import Path

import yaml


def parse_time(s: str | int | time) -> time:
    if isinstance(s, time):
        return s
    if isinstance(s, int):  # YAML 1.1 reads unquoted 15:45 as sexagesimal 945
        h, m = divmod(s, 60)
        return time(h, m)
    try:
        h, m = str(s).split(":")
        return time(int(h), int(m))
    except ValueError as e:
        raise ValueError(f"bad time {s!r}; use \"HH:MM\"") from e


@dataclass
class StrategyConfig:
    name: str = "orb"
    params: dict = field(default_factory=dict)  # validated by the strategy's Params dataclass


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.005    # fraction of equity lost if stop is hit
    max_position_pct: float = 0.25   # max notional per position as fraction of equity
    max_positions: int = 3           # concurrent positions + pending entries
    max_gross_pct: float = 1.0       # total notional of open positions as fraction of equity
    daily_max_loss: float = 0.02     # halt + flatten when down this much on the day
    flatten_at: time = time(15, 45)  # flatten everything at/after this time
    min_stop_pct: float = 0.001      # reject signals whose stop is closer than this (sizing blow-up guard)
    max_signal_delay_minutes: float = 2.0  # reject entries from bars that completed (arrived) late


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


def _symbols(v, path) -> list[str]:
    if not isinstance(v, list):
        raise ValueError(f"{path}: symbols must be a YAML list, e.g. [SPY, QQQ]")
    return [str(x).upper() for x in v]


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
        symbols=_symbols(raw.get("symbols", ["SPY", "QQQ"]), path),
        bar_minutes=int(raw.get("bar_minutes", 5)),
        strategy=StrategyConfig(name=s.get("name", "orb"), params=s.get("params") or {}),
        risk=build_dataclass(RiskConfig, raw.get("risk")),
        backtest=build_dataclass(BacktestConfig, raw.get("backtest")),
        live=build_dataclass(LiveConfig, raw.get("live")),
    )
    validate_config(cfg, str(path))
    return cfg


def validate_config(cfg: Config, where: str = "config") -> None:
    def bad(msg):
        raise ValueError(f"{where}: {msg}")

    if not isinstance(cfg.symbols, list) or not cfg.symbols or not all(isinstance(x, str) for x in cfg.symbols):
        bad("symbols must be a non-empty list")
    if cfg.bar_minutes <= 0 or 30 % cfg.bar_minutes:
        bad("bar_minutes must divide 30 (1, 2, 3, 5, 6, 10, 15, 30)")
    r = cfg.risk
    for k in ("risk_per_trade", "max_position_pct", "daily_max_loss", "min_stop_pct"):
        if not 0 < getattr(r, k) <= 1:
            bad(f"risk.{k} must be in (0, 1]")
    if not 0 < r.max_gross_pct <= 4:
        bad("risk.max_gross_pct must be in (0, 4]")
    if r.max_positions < 1:
        bad("risk.max_positions must be >= 1")
    if not (time(9, 30) < r.flatten_at < time(16, 0)):
        bad("risk.flatten_at must be between 09:30 and 16:00")
    if not cfg.name.replace("_", "").replace("-", "").isalnum():
        bad("name must be alphanumeric (plus - and _)")


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
