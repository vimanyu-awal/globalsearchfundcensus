"""Price + liquidity data — the one fragile dependency, isolated here.

SPEC treats price data as unreliable: yfinance primary, Stooq CSV fallback, and
if both fail for a ticker we mark PRICE_UNKNOWN and continue (never guess).

Returned figures:
    last_close   most recent daily close (USD, for market cap)
    adv20        20-day average daily *dollar* volume = mean(close * volume)
    source       "yfinance" | "stooq" | None
Everything is cached under data/raw/prices/ so re-runs are idempotent and do not
re-hit the price APIs.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

from . import config


@dataclass
class PriceInfo:
    last_close: float | None
    adv20: float | None
    source: str | None            # provenance
    asof: str | None              # date of the last close used
    yf_shares: float | None = None  # yfinance sharesOutstanding, for the multi-class cross-check

    @property
    def unknown(self) -> bool:
        return self.last_close is None


def _cache_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace(".", "_").upper()
    return config.RAW_DIR / "prices" / f"{safe}.json"


def _from_cache(ticker: str) -> PriceInfo | None:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return PriceInfo(**data)


def _to_cache(ticker: str, info: PriceInfo) -> None:
    path = _cache_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(info)))


def _adv_and_close(closes: list[float], volumes: list[float]) -> tuple[float | None, float | None, ]:
    """Compute (last_close, adv20) from parallel close/volume series."""
    if not closes:
        return None, None
    last_close = closes[-1]
    n = min(20, len(closes))
    dollar_vol = [c * v for c, v in zip(closes[-n:], volumes[-n:]) if c is not None and v is not None]
    adv20 = sum(dollar_vol) / len(dollar_vol) if dollar_vol else None
    return last_close, adv20


def _try_yfinance(ticker: str) -> PriceInfo | None:
    try:
        import yfinance as yf  # imported lazily so the rest of Phase 1 runs without it
    except ImportError:
        return None
    try:
        hist = yf.Ticker(ticker).history(period="3mo", auto_adjust=False)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    closes = [float(x) for x in hist["Close"].tolist()]
    volumes = [float(x) for x in hist["Volume"].tolist()]
    last_close, adv20 = _adv_and_close(closes, volumes)
    if last_close is None:
        return None
    asof = str(hist.index[-1].date())
    yf_shares = None
    try:
        shares = yf.Ticker(ticker).get_shares_full(start=None)
        if shares is not None and len(shares) > 0:
            yf_shares = float(shares.iloc[-1])
    except Exception:
        yf_shares = None
    return PriceInfo(last_close=last_close, adv20=adv20, source="yfinance", asof=asof, yf_shares=yf_shares)


def _try_stooq(ticker: str) -> PriceInfo | None:
    # Stooq wants US tickers suffixed ".us" and dotted classes hyphenated.
    symbol = ticker.replace(".", "-").lower() + ".us"
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        resp = requests.get(url, timeout=config.SEC_TIMEOUT_SECONDS)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or not resp.text or resp.text.startswith("<"):
        return None
    import pandas as pd

    try:
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception:
        return None
    if df.empty or "Close" not in df.columns or "Volume" not in df.columns:
        return None
    closes = [float(x) for x in df["Close"].tolist()]
    volumes = [float(x) for x in df["Volume"].tolist()]
    last_close, adv20 = _adv_and_close(closes, volumes)
    if last_close is None:
        return None
    asof = str(df["Date"].iloc[-1]) if "Date" in df.columns else None
    return PriceInfo(last_close=last_close, adv20=adv20, source="stooq", asof=asof)


def get_price(ticker: str, *, refresh: bool = False) -> PriceInfo:
    """Latest close + 20-day ADV for one ticker, with fallback chain."""
    if not refresh:
        cached = _from_cache(ticker)
        if cached is not None:
            return cached

    info = _try_yfinance(ticker) or _try_stooq(ticker)
    if info is None:
        info = PriceInfo(last_close=None, adv20=None, source=None, asof=None)  # PRICE_UNKNOWN
    _to_cache(ticker, info)
    return info
