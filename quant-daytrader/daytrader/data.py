"""Historical 1-minute data: Alpaca download with a local parquet cache, plus a
synthetic generator for tests and offline demos."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from .models import NY, Bar

log = logging.getLogger(__name__)
COLUMNS = ["symbol", "ts", "open", "high", "low", "close", "volume"]


def _month_starts(start: date, end: date) -> Iterator[date]:
    d = start.replace(day=1)
    while d <= end:
        yield d
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def fetch_alpaca_minutes(symbols: list[str], start: date, end: date, feed: str = "sip",
                         cache_dir: str | Path = "data/cache", account_env: str = "ALPACA") -> pd.DataFrame:
    """Download split-adjusted 1-minute bars, cached per symbol-month (current month is never cached)."""
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    from .config import alpaca_keys

    key, secret = alpaca_keys(account_env)
    client = StockHistoricalDataClient(key, secret)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    frames = []
    today = datetime.now(NY).date()
    for sym in symbols:
        for m in _month_starts(start, end):
            m_end = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
            path = cache / f"{sym}_{m:%Y%m}_{feed}.parquet"
            complete_month = m_end <= today
            if complete_month and path.exists():
                frames.append(pd.read_parquet(path))
                continue
            log.info("downloading %s %s", sym, f"{m:%Y-%m}")
            req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Minute,
                                   start=datetime.combine(m, time(), NY), end=datetime.combine(m_end, time(), NY),
                                   adjustment=Adjustment.SPLIT, feed=DataFeed(feed))
            req_end = min(datetime.combine(m_end, time(), NY), datetime.now(NY) - timedelta(minutes=20))
            if req_end <= datetime.combine(m, time(), NY):
                continue
            req = req.model_copy(update={"end": req_end})  # free plan: no SIP data from the last 15 min
            df = client.get_stock_bars(req).df
            if df.empty:
                continue
            df = df.reset_index().rename(columns={"timestamp": "ts"})
            df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(NY)
            df = df[COLUMNS]
            if complete_month:
                df.to_parquet(path, index=False)
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    lo = datetime.combine(start, time(), NY)
    hi = datetime.combine(end + timedelta(days=1), time(), NY)
    return df[(df.ts >= lo) & (df.ts < hi)].reset_index(drop=True)


def synthetic_minutes(symbols: list[str], days: int = 60, seed: int = 7,
                      start: date = date(2025, 1, 6), trend: float = 0.00012,
                      gap_sd: float = 0.006) -> pd.DataFrame:
    """Random-walk regular-hours minute bars with a U-shaped volume profile and
    occasional trend days. For testing the plumbing only - NOT for strategy research."""
    rng = np.random.default_rng(seed)
    rows = []
    sessions = pd.bdate_range(start, periods=days)
    minutes = np.arange(390)
    vol_profile = 1.0 + 2.5 * np.exp(-minutes / 25) + 1.2 * np.exp(-(389 - minutes) / 30)
    for sym in symbols:
        price = float(rng.uniform(80, 400))
        for d in sessions:
            drift = rng.choice([0.0, 0.0, 0.0, 1.0, -1.0]) * trend
            rets = rng.normal(drift, 0.0009, 390)
            gap = rng.normal(0, gap_sd)
            closes = price * (1 + gap) * np.exp(np.cumsum(rets))
            opens = np.concatenate([[price * (1 + gap)], closes[:-1]])
            spread = np.abs(rng.normal(0, 0.0005, 390)) * closes
            highs = np.maximum(opens, closes) + spread
            lows = np.minimum(opens, closes) - spread
            vols = (vol_profile * rng.lognormal(10, 0.4, 390)).round()
            t0 = datetime.combine(d.date(), time(9, 30), NY)
            for i in range(390):
                rows.append((sym, t0 + timedelta(minutes=i), opens[i], highs[i], lows[i], closes[i], vols[i]))
            price = float(closes[-1])
    return pd.DataFrame(rows, columns=COLUMNS)


def iter_bars(df: pd.DataFrame) -> Iterator[Bar]:
    """Yield bars in time order across symbols (ties broken by symbol)."""
    df = df.sort_values(["ts", "symbol"], kind="stable")
    for r in df.itertuples(index=False):
        ts = r.ts.to_pydatetime() if hasattr(r.ts, "to_pydatetime") else r.ts
        yield Bar(r.symbol, ts, float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume))
