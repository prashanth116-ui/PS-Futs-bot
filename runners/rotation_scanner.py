"""Sector Rotation Scanner - Identify quality stocks in rotating sectors.

Calculates sector rotation signals for 13 GICS sectors using ETF proxies,
identifies stocks in rotating sectors, applies quality gates, scores conviction,
and sends Telegram alerts.

Usage:
    python -m runners.rotation_scanner                    # Full scan + Telegram
    python -m runners.rotation_scanner --dry-run          # Print only
    python -m runners.rotation_scanner --sector SMH       # Single sector
    python -m runners.rotation_scanner --sector SMH,XLF   # Multiple sectors
    python -m runners.rotation_scanner --verbose          # Detailed logging
    python -m runners.rotation_scanner --force-refresh    # Bypass daily cache
    python -m runners.rotation_scanner --min-conviction MEDIUM
"""

import argparse
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from runners.notifier import get_notifier

# Load environment variables
_env_path = Path(__file__).parent.parent / "config" / ".env"
load_dotenv(_env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rotation_scanner")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).parent.parent / "data" / "rotation"
_STATE_PATH = _DATA_DIR / "state.json"
_CACHE_DIR = _DATA_DIR / "cache"

# ---------------------------------------------------------------------------
# Sector Universe
# ---------------------------------------------------------------------------
SECTOR_ETFS = {
    "SMH": "Semiconductors",
    "IGV": "Software",
    "XLK": "Technology",
    "XBI": "Biotech",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLY": "Consumer Disc",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication",
    "XLB": "Materials",
}

BENCHMARK = "SPY"

# ~15 major holdings per ETF (large-cap, liquid)
SECTOR_HOLDINGS = {
    "SMH": ["NVDA", "AMD", "AVGO", "INTC", "QCOM", "TXN", "MU", "MRVL",
            "AMAT", "LRCX", "KLAC", "ADI", "NXPI", "ON", "MCHP"],
    "IGV": ["MSFT", "CRM", "ADBE", "NOW", "ORCL", "INTU", "SNPS", "CDNS",
            "PANW", "WDAY", "ADSK", "ANSS", "FTNT", "DDOG", "ZS"],
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "CRM", "ADBE", "AMD", "ORCL",
            "CSCO", "ACN", "IBM", "INTC", "INTU", "NOW", "TXN"],
    "XLF": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS",
            "SPGI", "AXP", "BLK", "C", "SCHW", "CB", "MMC"],
    "XLE": ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "PXD",
            "VLO", "OXY", "HES", "DVN", "HAL", "FANG", "BKR"],
    "XLV": ["UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT",
            "DHR", "BMY", "AMGN", "ISRG", "MDT", "GILD", "SYK"],
    "XLI": ["GE", "CAT", "HON", "UNP", "RTX", "BA", "DE", "LMT",
            "ADP", "MMM", "GD", "ITW", "WM", "CSX", "NOC"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX",
            "BKNG", "CMG", "ORLY", "MAR", "DHI", "GM", "F"],
    "XLP": ["PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "CL",
            "MDLZ", "EL", "KHC", "GIS", "SJM", "STZ", "KMB"],
    "XLU": ["NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL",
            "ED", "WEC", "ES", "PEG", "AWK", "DTE", "PPL"],
    "XLRE": ["PLD", "AMT", "CCI", "EQIX", "PSA", "O", "WELL", "DLR",
             "SPG", "VICI", "AVB", "EQR", "IRM", "ARE", "MAA"],
    "XLC": ["META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "T", "VZ",
            "CHTR", "TMUS", "EA", "TTWO", "WBD", "LYV", "OMC"],
    "XLB": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DOW",
            "DD", "VMC", "MLM", "PPG", "CTVA", "ALB", "CE"],
    "XBI": ["BIIB", "ALNY", "BGNE", "EXEL", "INCY", "IONS", "HALO",
            "INSM", "BMRN", "JAZZ", "BNTX", "CRSP", "ILMN", "ITCI", "CORT"],
}

# ---------------------------------------------------------------------------
# Composite Score Weights
# ---------------------------------------------------------------------------
W_MOMENTUM = 0.25
W_ACCELERATION = 0.15
W_MANSFIELD_RS = 0.20
W_CMF = 0.15
W_BREADTH = 0.15
W_SMART_MONEY = 0.10

# Conviction signal thresholds
CONVICTION_SIGNALS = {
    "sector_improving_or_leading": True,
    "composite_gte_70": 70,
    "turnaround_or_leader": True,
    "rs_accel_gte_3": 3.0,
    "stealth_accumulation": True,
    "volume_gte_1_2": 1.2,
    "institutional_gt_50": 50,
}

# Dedup timing
DEDUP_DAYS = 3
DEDUP_EXPIRY_DAYS = 14


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

def _ensure_dirs():
    """Create data directories if needed."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(label: str) -> Path:
    return _CACHE_DIR / f"{date.today().isoformat()}_{label}.json"


def _load_cache(label: str) -> Optional[dict]:
    p = _cache_path(label)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_cache(label: str, data: dict):
    _ensure_dirs()
    p = _cache_path(label)
    p.write_text(json.dumps(data, default=str))


def _df_cache_path(label: str) -> Path:
    return _CACHE_DIR / f"{date.today().isoformat()}_{label}.parquet"


def _save_df_cache(label: str, df: pd.DataFrame):
    """Save a DataFrame to parquet cache (preserves MultiIndex)."""
    _ensure_dirs()
    df.to_parquet(_df_cache_path(label))


def _load_df_cache(label: str) -> Optional[pd.DataFrame]:
    """Load a cached DataFrame from parquet."""
    p = _df_cache_path(label)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except (ValueError, OSError):
        return None


def fetch_etf_data(force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """Fetch 1 year daily data for all sector ETFs + SPY in one bulk call."""
    if not force_refresh:
        cached = _load_df_cache("etf_prices")
        if cached is not None:
            log.info("Using cached ETF price data")
            return cached

    tickers = list(SECTOR_ETFS.keys()) + [BENCHMARK]
    log.info("Downloading 1Y daily data for %d ETFs...", len(tickers))

    for attempt in range(3):
        try:
            df = yf.download(tickers, period="1y", interval="1d",
                             group_by="ticker", progress=False, threads=True)
            if df is not None and not df.empty:
                _save_df_cache("etf_prices", df)
                log.info("ETF data: %d rows x %d columns", len(df), len(df.columns))
                return df
            log.warning("Empty ETF data on attempt %d", attempt + 1)
        except Exception as e:
            log.warning("ETF download attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    log.error("Failed to download ETF data after 3 attempts")
    return None


def fetch_stock_prices(symbols: List[str], force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """Fetch 1 year daily data for candidate stocks."""
    cache_label = "stock_prices_" + "_".join(sorted(symbols)[:5])
    if not force_refresh:
        cached = _load_df_cache(cache_label)
        if cached is not None:
            log.info("Using cached stock price data (%d symbols)", len(symbols))
            return cached

    log.info("Downloading 1Y daily data for %d stocks...", len(symbols))
    for attempt in range(3):
        try:
            df = yf.download(symbols, period="1y", interval="1d",
                             group_by="ticker", progress=False, threads=True)
            if df is not None and not df.empty:
                _save_df_cache(cache_label, df)
                return df
        except Exception as e:
            log.warning("Stock download attempt %d failed: %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(2)
    log.error("Failed to download stock data after 3 attempts")
    return None


def fetch_stock_info(symbol: str, force_refresh: bool = False) -> Dict:
    """Fetch fundamental info for a single stock (cached daily)."""
    cache_label = f"info_{symbol}"
    cache = None if force_refresh else _load_cache(cache_label)
    if cache is not None:
        return cache

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        result = {
            "market_cap": info.get("marketCap"),
            "institutional_pct": _parse_inst_pct(info),
            "short_name": info.get("shortName", symbol),
        }
        _save_cache(cache_label, result)
        return result
    except Exception as e:
        log.debug("Info fetch failed for %s: %s", symbol, e)
        return {"market_cap": None, "institutional_pct": None, "short_name": symbol}


def _parse_inst_pct(info: dict) -> Optional[float]:
    """Extract institutional ownership % from yfinance info."""
    pct = info.get("heldPercentInstitutions")
    if pct is not None:
        return round(pct * 100, 1)
    return None


# ---------------------------------------------------------------------------
# Step 1: Sector Analysis
# ---------------------------------------------------------------------------

def _get_close(df: pd.DataFrame, ticker: str) -> pd.Series:
    """Extract close prices for a ticker from grouped DataFrame."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            return df[(ticker, "Close")].dropna()
        return df["Close"].dropna()
    except (KeyError, TypeError):
        return pd.Series(dtype=float)


def _get_volume(df: pd.DataFrame, ticker: str) -> pd.Series:
    """Extract volume for a ticker from grouped DataFrame."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            return df[(ticker, "Volume")].dropna()
        return df["Volume"].dropna()
    except (KeyError, TypeError):
        return pd.Series(dtype=float)


def _get_high(df: pd.DataFrame, ticker: str) -> pd.Series:
    try:
        if isinstance(df.columns, pd.MultiIndex):
            return df[(ticker, "High")].dropna()
        return df["High"].dropna()
    except (KeyError, TypeError):
        return pd.Series(dtype=float)


def _get_low(df: pd.DataFrame, ticker: str) -> pd.Series:
    try:
        if isinstance(df.columns, pd.MultiIndex):
            return df[(ticker, "Low")].dropna()
        return df["Low"].dropna()
    except (KeyError, TypeError):
        return pd.Series(dtype=float)


def calc_roc(series: pd.Series, period: int) -> pd.Series:
    """Rate of change: (current - N periods ago) / N periods ago * 100."""
    return series.pct_change(periods=period) * 100


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def calc_cmf(high: pd.Series, low: pd.Series, close: pd.Series,
             volume: pd.Series, period: int = 20) -> pd.Series:
    """Chaikin Money Flow."""
    hl_range = high - low
    hl_range = hl_range.replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / hl_range
    mfv = mfm * volume
    cmf = mfv.rolling(window=period).sum() / volume.rolling(window=period).sum()
    return cmf


def normalize_0_100(series: pd.Series) -> pd.Series:
    """Normalize a series to 0-100 range using min-max."""
    s_min = series.min()
    s_max = series.max()
    if s_max == s_min:
        return pd.Series(50.0, index=series.index)
    return (series - s_min) / (s_max - s_min) * 100


def analyze_sector(etf: str, etf_df: pd.DataFrame, spy_close: pd.Series) -> Optional[Dict]:
    """Compute all rotation signals for one sector ETF."""
    close = _get_close(etf_df, etf)
    volume = _get_volume(etf_df, etf)
    high = _get_high(etf_df, etf)
    low = _get_low(etf_df, etf)

    if len(close) < 200:
        log.debug("Insufficient data for %s (%d bars)", etf, len(close))
        return None

    # Align with SPY
    common_idx = close.index.intersection(spy_close.index)
    close = close.loc[common_idx]
    spy = spy_close.loc[common_idx]
    volume = volume.reindex(common_idx).fillna(0)
    high = high.reindex(common_idx).fillna(close)
    low = low.reindex(common_idx).fillna(close)

    if len(close) < 200:
        return None

    # --- Momentum (25%): avg ROC at 63/126/189/252 days ---
    roc_periods = [p for p in [63, 126, 189, 252] if p < len(close)]
    rocs = []
    for p in roc_periods:
        r = calc_roc(close, p)
        if not r.empty and not np.isnan(r.iloc[-1]):
            rocs.append(r.iloc[-1])
    momentum_raw = np.mean(rocs) if rocs else 0.0

    # --- Acceleration (15%): 21-day ROC of the 63-day ROC ---
    roc63 = calc_roc(close, 63)
    accel_series = calc_roc(roc63, 21)
    acceleration = accel_series.iloc[-1] if not np.isnan(accel_series.iloc[-1]) else 0.0

    # --- Mansfield RS (20%) ---
    rs_line = close / spy
    sma_period = min(200, len(rs_line) - 1)
    rs_sma52 = calc_sma(rs_line, sma_period)
    mansfield = ((rs_line / rs_sma52) - 1) * 100
    mansfield_val = mansfield.iloc[-1] if not np.isnan(mansfield.iloc[-1]) else 0.0

    # --- CMF (15%) ---
    cmf = calc_cmf(high, low, close, volume, 20)
    cmf_val = cmf.iloc[-1] if not np.isnan(cmf.iloc[-1]) else 0.0

    # --- Breadth (15%): % of sector stocks above 50-day SMA ---
    # Deferred to after stock data fetch; use placeholder
    breadth_pct = None  # filled later

    # --- Smart Money (10%): avg institutional ownership ---
    # Deferred; use placeholder
    smart_money_pct = None  # filled later

    # --- RRG Quadrant (JdK-standard: EMA smooth + Z-score normalization) ---
    rs_smooth = rs_line.ewm(span=10, adjust=False).mean()
    # Cap at 200 (not 250) to ensure valid Z-scores with ~252 trading days of data
    lookback = min(200, len(rs_smooth) - 30)
    if lookback < 20:
        lookback = len(rs_smooth)  # fallback

    z_rs = (rs_smooth - rs_smooth.rolling(lookback).mean()) / rs_smooth.rolling(lookback).std()
    rs_ratio_series = 100 + z_rs.fillna(0)
    rs_ratio = rs_ratio_series.iloc[-1]

    roc_rs = calc_roc(rs_ratio_series, 10)
    roc_rs_clean = roc_rs.dropna()
    if len(roc_rs_clean) >= lookback:
        z_mom = (roc_rs_clean - roc_rs_clean.rolling(lookback).mean()) / roc_rs_clean.rolling(lookback).std()
        rs_momentum_series = 100 + z_mom.fillna(0)
    else:
        rs_momentum_series = 100 + roc_rs.fillna(0) * 0  # fallback: flat at 100
    rs_momentum = rs_momentum_series.iloc[-1] if not np.isnan(rs_momentum_series.iloc[-1]) else 100.0

    if rs_ratio >= 100 and rs_momentum >= 100:
        quadrant = "LEADING"
    elif rs_ratio >= 100 and rs_momentum < 100:
        quadrant = "WEAKENING"
    elif rs_ratio < 100 and rs_momentum < 100:
        quadrant = "LAGGING"
    else:
        quadrant = "IMPROVING"

    # --- Stealth Accumulation ---
    ret_20d = calc_roc(close, 20).iloc[-1] if len(close) >= 20 else 0.0
    if np.isnan(ret_20d):
        ret_20d = 0.0

    cmf_positive_days = (cmf.tail(20) > 0).sum() if len(cmf) >= 20 else 0
    flow_price_div = cmf_positive_days >= 15 and ret_20d < 0

    # Breadth divergence deferred
    breadth_div = False  # updated later

    accel_inflection = acceleration > 0 and ret_20d < 0

    stealth_signals = sum([flow_price_div, breadth_div, accel_inflection])
    stealth_accumulation = stealth_signals >= 2

    return {
        "etf": etf,
        "name": SECTOR_ETFS[etf],
        "momentum_raw": momentum_raw,
        "acceleration": acceleration,
        "mansfield_rs": mansfield_val,
        "rs_ratio": rs_ratio,
        "rs_momentum": rs_momentum,
        "cmf": cmf_val,
        "cmf_positive_days": int(cmf_positive_days),
        "breadth_pct": breadth_pct,
        "smart_money_pct": smart_money_pct,
        "quadrant": quadrant,
        "ret_20d": ret_20d,
        "stealth_accumulation": stealth_accumulation,
        "stealth_signals": stealth_signals,
        "flow_price_div": flow_price_div,
        "accel_inflection": accel_inflection,
        "breadth_div": breadth_div,
        "composite": None,  # calculated after breadth/smart_money filled
    }


def compute_composite(sector: Dict) -> float:
    """Compute the composite score (0-100) for a sector."""
    # Normalize individual factors to 0-100 for combination
    # Momentum: use raw value, clamp to reasonable range [-30, +30]
    mom = np.clip(sector["momentum_raw"], -30, 30)
    mom_score = (mom + 30) / 60 * 100

    # Acceleration: clamp [-10, +10]
    acc = np.clip(sector["acceleration"], -10, 10)
    acc_score = (acc + 10) / 20 * 100

    # Mansfield RS: clamp [-20, +20]
    mrs = np.clip(sector["mansfield_rs"], -20, 20)
    mrs_score = (mrs + 20) / 40 * 100

    # CMF: clamp [-0.5, +0.5]
    cmf = np.clip(sector["cmf"], -0.5, 0.5)
    cmf_score = (cmf + 0.5) / 1.0 * 100

    # Breadth: already 0-100 (or None)
    breadth = sector.get("breadth_pct") or 50.0
    breadth_score = np.clip(breadth, 0, 100)

    # Smart money: already % (or None)
    smart = sector.get("smart_money_pct") or 50.0
    smart_score = np.clip(smart, 0, 100)

    composite = (
        W_MOMENTUM * mom_score
        + W_ACCELERATION * acc_score
        + W_MANSFIELD_RS * mrs_score
        + W_CMF * cmf_score
        + W_BREADTH * breadth_score
        + W_SMART_MONEY * smart_score
    )
    return round(np.clip(composite, 0, 100), 1)


def analyze_all_sectors(etf_df: pd.DataFrame) -> List[Dict]:
    """Step 1: Analyze all 13 sectors."""
    spy_close = _get_close(etf_df, BENCHMARK)
    if spy_close.empty:
        log.error("No SPY data available")
        return []

    sectors = []
    for etf in SECTOR_ETFS:
        result = analyze_sector(etf, etf_df, spy_close)
        if result:
            sectors.append(result)
        else:
            log.warning("Skipped %s (insufficient data)", etf)
    return sectors


# ---------------------------------------------------------------------------
# Step 2: Filter to Interesting Sectors
# ---------------------------------------------------------------------------

def filter_interesting_sectors(sectors: List[Dict]) -> List[Dict]:
    """Only process sectors where rotation signals are present."""
    interesting = []
    for s in sectors:
        reasons = []
        if s["quadrant"] in ("IMPROVING", "LEADING"):
            reasons.append(f"quadrant={s['quadrant']}")
        if s["composite"] is not None and s["composite"] >= 60:
            reasons.append(f"composite={s['composite']}")
        if s["stealth_accumulation"]:
            reasons.append("stealth_accumulation")
        if s["acceleration"] > 2.0:
            reasons.append(f"acceleration={s['acceleration']:.1f}")

        if reasons:
            s["filter_reasons"] = reasons
            interesting.append(s)
    return interesting


# ---------------------------------------------------------------------------
# Step 3-4: Stock Enrichment
# ---------------------------------------------------------------------------

def get_candidate_stocks(interesting_sectors: List[Dict]) -> Dict[str, List[str]]:
    """Map interesting sectors to their stock holdings."""
    result = {}
    for s in interesting_sectors:
        etf = s["etf"]
        if etf in SECTOR_HOLDINGS:
            result[etf] = SECTOR_HOLDINGS[etf]
    return result


def enrich_stocks(
    sector_stocks: Dict[str, List[str]],
    etf_df: pd.DataFrame,
    sectors: List[Dict],
    force_refresh: bool = False,
) -> List[Dict]:
    """Step 4: Download stock prices and enrich with fundamentals."""
    # Collect all unique symbols
    all_symbols = set()
    for stocks in sector_stocks.values():
        all_symbols.update(stocks)
    all_symbols = sorted(all_symbols)

    if not all_symbols:
        return []

    log.info("Enriching %d candidate stocks...", len(all_symbols))

    # Bulk price download
    stock_df = fetch_stock_prices(all_symbols, force_refresh=force_refresh)
    if stock_df is None:
        log.error("Failed to fetch stock prices")
        return []

    # Build sector lookup
    sector_map = {s["etf"]: s for s in sectors}

    enriched = []
    for etf, symbols in sector_stocks.items():
        sector = sector_map.get(etf)
        if not sector:
            continue

        etf_close = _get_close(etf_df, etf)
        etf_ret_20d = sector.get("ret_20d", 0.0)

        for sym in symbols:
            stock = _enrich_single_stock(sym, stock_df, etf, etf_close, etf_ret_20d,
                                         sector, force_refresh)
            if stock:
                enriched.append(stock)

    # Update sector breadth with actual stock data
    _update_sector_breadth(sectors, enriched)

    return enriched


def _enrich_single_stock(
    sym: str,
    stock_df: pd.DataFrame,
    etf: str,
    etf_close: pd.Series,
    etf_ret_20d: float,
    sector: Dict,
    force_refresh: bool,
) -> Optional[Dict]:
    """Enrich a single stock with price and fundamental data."""
    close = _get_close(stock_df, sym)
    vol = _get_volume(stock_df, sym)

    if len(close) < 200:
        log.debug("Skipping %s: insufficient price data (%d bars)", sym, len(close))
        return None

    price = close.iloc[-1]
    sma50 = calc_sma(close, 50).iloc[-1]
    sma200 = calc_sma(close, 200).iloc[-1]

    if np.isnan(price) or np.isnan(sma50) or np.isnan(sma200):
        return None

    vol_5d = vol.tail(5).mean() if len(vol) >= 5 else 0
    vol_20d = vol.tail(20).mean() if len(vol) >= 20 else 0
    vol_ratio = vol_5d / vol_20d if vol_20d > 0 else 1.0

    ret_20d = calc_roc(close, 20).iloc[-1] if len(close) >= 20 else 0.0
    if np.isnan(ret_20d):
        ret_20d = 0.0

    # RS acceleration: (5d outperformance vs ETF) - (20d outperformance vs ETF)
    common = close.index.intersection(etf_close.index)
    if len(common) >= 20:
        stk = close.loc[common]
        etf_c = etf_close.loc[common]
        stk_ret_5d = (stk.iloc[-1] / stk.iloc[-5] - 1) * 100 if len(stk) >= 5 else 0
        etf_ret_5d = (etf_c.iloc[-1] / etf_c.iloc[-5] - 1) * 100 if len(etf_c) >= 5 else 0
        stk_ret_20d = (stk.iloc[-1] / stk.iloc[-20] - 1) * 100
        etf_ret_20d_calc = (etf_c.iloc[-1] / etf_c.iloc[-20] - 1) * 100
        outperf_5d = stk_ret_5d - etf_ret_5d
        outperf_20d = stk_ret_20d - etf_ret_20d_calc
        rs_accel = outperf_5d - outperf_20d
    else:
        rs_accel = 0.0

    # Fetch fundamental info (individual call, cached)
    info = fetch_stock_info(sym, force_refresh=force_refresh)

    return {
        "symbol": sym,
        "etf": etf,
        "sector_name": sector["name"],
        "price": round(price, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "above_50ma": price > sma50,
        "pct_from_50ma": round((price / sma50 - 1) * 100, 1),
        "pct_from_200ma": round((price / sma200 - 1) * 100, 1),
        "vol_5d": round(vol_5d),
        "vol_20d": round(vol_20d),
        "vol_ratio": round(vol_ratio, 2),
        "ret_20d": round(ret_20d, 2),
        "etf_ret_20d": round(etf_ret_20d, 2),
        "rs_accel": round(rs_accel, 2),
        "market_cap": info.get("market_cap"),
        "institutional_pct": info.get("institutional_pct"),
        "short_name": info.get("short_name", sym),
        "sector_quadrant": sector["quadrant"],
        "sector_composite": sector.get("composite"),
        "sector_stealth": sector.get("stealth_accumulation", False),
        "sector_acceleration": sector.get("acceleration", 0.0),
    }


def _update_sector_breadth(sectors: List[Dict], enriched: List[Dict]):
    """Update sector breadth_pct using enriched stock data."""
    # Group stocks by ETF
    by_etf = {}
    for s in enriched:
        by_etf.setdefault(s["etf"], []).append(s)

    for sector in sectors:
        etf = sector["etf"]
        stocks = by_etf.get(etf, [])
        if stocks:
            above = sum(1 for s in stocks if s["above_50ma"])
            sector["breadth_pct"] = round(above / len(stocks) * 100, 1)
        else:
            sector["breadth_pct"] = 50.0  # default

        # Recalculate composite now that breadth is available
        sector["composite"] = compute_composite(sector)

        # Update breadth divergence for stealth detection
        if sector["breadth_pct"] > 50 and sector["ret_20d"] < 0:
            sector["breadth_div"] = True
            # Recount stealth signals
            signals = sum([
                sector.get("flow_price_div", False),
                sector["breadth_div"],
                sector.get("accel_inflection", False),
            ])
            sector["stealth_signals"] = signals
            sector["stealth_accumulation"] = signals >= 2


# ---------------------------------------------------------------------------
# Step 5: Quality Gates
# ---------------------------------------------------------------------------

def apply_quality_gates(stocks: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Apply 7 quality gates. Returns (passed, rejected)."""
    passed = []
    rejected = []

    for s in stocks:
        reasons = []

        # Gate 1: Market cap >= $2B
        mc = s.get("market_cap")
        if mc is not None and mc < 2_000_000_000:
            reasons.append(f"market_cap=${mc/1e9:.1f}B (<$2B)")

        # Gate 2: Avg daily volume >= 1M shares
        if s["vol_20d"] < 1_000_000:
            reasons.append(f"vol_20d={s['vol_20d']/1e6:.1f}M (<1M)")

        # Gate 3: Volume spike ratio <= 5x
        if s["vol_ratio"] > 5.0:
            reasons.append(f"vol_spike={s['vol_ratio']:.1f}x (>5x)")

        # Gate 4: Price extension <= 80% above 200-SMA
        if s["pct_from_200ma"] > 80:
            reasons.append(f"extension={s['pct_from_200ma']:.0f}% (>80%)")

        # Gate 5: Above 50-SMA or turnaround signal
        if not s["above_50ma"] and not (s["rs_accel"] > 0.5 and s["vol_ratio"] >= 1.0):
            reasons.append("below_50MA_no_turnaround")

        # Gate 6: Institutional ownership > 30% (skip if unavailable)
        inst = s.get("institutional_pct")
        if inst is not None and inst < 30:
            reasons.append(f"institutional={inst:.0f}% (<30%)")

        # Gate 7: Sector correlation (20d return within 2 std devs of sector ETF)
        ret_diff = abs(s["ret_20d"] - s["etf_ret_20d"])
        if ret_diff > 30:  # rough 2-sigma proxy
            reasons.append(f"uncorrelated_ret_diff={ret_diff:.1f}%")

        if reasons:
            s["rejection_reasons"] = reasons
            rejected.append(s)
        else:
            passed.append(s)

    return passed, rejected


# ---------------------------------------------------------------------------
# Step 6: Classification
# ---------------------------------------------------------------------------

def classify_stock(s: Dict) -> Dict:
    """Classify a stock by category and lifecycle phase."""
    # Category
    if s["above_50ma"] and s["ret_20d"] > s["etf_ret_20d"] and s["vol_ratio"] >= 1.0:
        category = "LEADER"
    elif s["above_50ma"]:
        category = "CATCH_UP"
    elif s["rs_accel"] > 0.5 and s["vol_ratio"] >= 1.0:
        category = "TURNAROUND"
    else:
        category = "AVOID"

    # Lifecycle phase
    pct_50ma = s["pct_from_50ma"]
    if not s["above_50ma"] and s["rs_accel"] > 0:
        phase = "P1_BASING"
    elif -5 <= pct_50ma <= 3 and s["rs_accel"] > 0.5 and s["vol_ratio"] >= 1.2:
        phase = "P2_TURNAROUND"
    elif pct_50ma > 3 and s["rs_accel"] >= 0:
        phase = "P3_TRENDING"
    elif s["rs_accel"] < -2.0 or s.get("sector_acceleration", 0) < -3:
        phase = "P4_EXHAUSTING"
    else:
        phase = "P3_TRENDING" if s["above_50ma"] else "P1_BASING"

    s["category"] = category
    s["phase"] = phase

    # RS acceleration description
    if s["rs_accel"] >= 3.0:
        s["rs_accel_desc"] = "strong catch-up"
    elif s["rs_accel"] >= 0.5:
        s["rs_accel_desc"] = "moderate"
    elif s["rs_accel"] >= -0.5:
        s["rs_accel_desc"] = "neutral"
    else:
        s["rs_accel_desc"] = "decelerating"

    return s


# ---------------------------------------------------------------------------
# Step 7: Conviction Scoring
# ---------------------------------------------------------------------------

def score_conviction(s: Dict) -> Dict:
    """Score conviction as HIGH, MEDIUM, or WATCH."""
    signals = 0

    if s["sector_quadrant"] in ("IMPROVING", "LEADING"):
        signals += 1
    if s.get("sector_composite") is not None and s["sector_composite"] >= 70:
        signals += 1
    if s["category"] in ("TURNAROUND", "LEADER"):
        signals += 1
    if s["rs_accel"] >= 3.0:
        signals += 1
    if s.get("sector_stealth", False):
        signals += 1
    if s["vol_ratio"] >= 1.2:
        signals += 1
    inst = s.get("institutional_pct")
    if inst is not None and inst > 50:
        signals += 1

    if signals >= 3:
        conviction = "HIGH"
    elif signals >= 2:
        conviction = "MEDIUM"
    else:
        conviction = "WATCH"

    s["conviction"] = conviction
    s["conviction_signals"] = signals
    return s


# ---------------------------------------------------------------------------
# Step 8: Dedup & Alerting
# ---------------------------------------------------------------------------

def _load_state() -> Dict:
    """Load alert state (previously alerted stocks)."""
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {"alerts": {}}
    return {"alerts": {}}


def _save_state(state: Dict):
    _ensure_dirs()
    _STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def should_alert(sym: str, conviction: str, category: str, phase: str, state: Dict) -> bool:
    """Check if we should send an alert for this stock (dedup logic)."""
    key = sym
    today = date.today()
    alerts = state.get("alerts", {})

    if key not in alerts:
        return True

    prev = alerts[key]
    prev_date = date.fromisoformat(prev["date"])
    days_since = (today - prev_date).days

    # Clean old entries
    if days_since > DEDUP_EXPIRY_DAYS:
        return True

    prev_conviction = prev.get("conviction", "WATCH")
    prev_category = prev.get("category", "")
    prev_phase = prev.get("phase", "")

    # Conviction upgrade: re-alert
    conviction_order = {"WATCH": 0, "MEDIUM": 1, "HIGH": 2}
    if conviction_order.get(conviction, 0) > conviction_order.get(prev_conviction, 0):
        return True

    # Category change: re-alert
    if category != prev_category:
        return True

    # Phase transition: re-alert
    if phase != prev_phase:
        return True

    # Same stock/conviction: skip if within DEDUP_DAYS
    if days_since < DEDUP_DAYS:
        return False

    return True


def record_alert(sym: str, conviction: str, category: str, phase: str, state: Dict):
    """Record an alert in state."""
    state.setdefault("alerts", {})[sym] = {
        "date": date.today().isoformat(),
        "conviction": conviction,
        "category": category,
        "phase": phase,
    }


def clean_state(state: Dict):
    """Remove entries older than DEDUP_EXPIRY_DAYS."""
    today = date.today()
    alerts = state.get("alerts", {})
    to_remove = []
    for sym, data in alerts.items():
        try:
            d = date.fromisoformat(data["date"])
            if (today - d).days > DEDUP_EXPIRY_DAYS:
                to_remove.append(sym)
        except (KeyError, ValueError):
            to_remove.append(sym)
    for sym in to_remove:
        del alerts[sym]


# ---------------------------------------------------------------------------
# Telegram Formatting
# ---------------------------------------------------------------------------

def format_sector_alert(sector: Dict, stocks: List[Dict]) -> str:
    """Format a sector summary Telegram message (HTML)."""
    high = sum(1 for s in stocks if s.get("conviction") == "HIGH")
    medium = sum(1 for s in stocks if s.get("conviction") == "MEDIUM")
    watch = sum(1 for s in stocks if s.get("conviction") == "WATCH")

    stealth = "\nSTEALTH ACCUMULATION" if sector.get("stealth_accumulation") else ""

    breadth = sector.get("breadth_pct")
    breadth_str = f"{breadth:.0f}%" if breadth is not None else "N/A"

    msg = (
        f"<b>SECTOR ROTATION | {sector['name']} ({sector['etf']})</b>\n"
        f"Quadrant: <b>{sector['quadrant']}</b> | Composite: {sector.get('composite', 'N/A')}/100\n"
        f"RS: {sector['rs_ratio']:.1f} | Breadth: {breadth_str} above 50MA\n"
        f"CMF: {sector['cmf']:+.3f}{stealth}\n"
        f"{len(stocks)} stocks qualify | {high} HIGH, {medium} MEDIUM, {watch} WATCH"
    )
    return msg


def format_stock_alert(s: Dict) -> str:
    """Format a stock pick Telegram message (HTML)."""
    inst_str = f"{s['institutional_pct']:.0f}%" if s.get("institutional_pct") is not None else "N/A"
    mc = s.get("market_cap")
    mc_str = f"${mc/1e9:.1f}B" if mc is not None else "N/A"

    msg = (
        f"<b>ROTATION PICK | {s['symbol']}</b> ({s['short_name']})\n"
        f"Sector: {s['sector_name']} ({s['etf']}) | {s['sector_quadrant']}\n"
        f"Category: <b>{s['category']}</b> | Phase: {s['phase']}\n"
        f"\nConviction: <b>{s['conviction']}</b>\n"
        f"- RS Acceleration: {s['rs_accel']:+.2f} ({s['rs_accel_desc']})\n"
        f"- Volume: {s['vol_ratio']:.1f}x avg\n"
        f"- Institutional: {inst_str}\n"
        f"\nPrice: ${s['price']:.2f} | 50-SMA: ${s['sma50']:.2f} ({s['pct_from_50ma']:+.1f}%)\n"
        f"Mkt Cap: {mc_str} | Avg Vol: {s['vol_20d']/1e6:.1f}M"
    )
    return msg


# ---------------------------------------------------------------------------
# Console Output
# ---------------------------------------------------------------------------

def print_sector_summary(sectors: List[Dict], interesting: List[Dict]):
    """Print sector analysis to console."""
    print("\n" + "=" * 70)
    print("SECTOR ROTATION ANALYSIS")
    print("=" * 70)

    # Sort by composite score descending
    sorted_sectors = sorted(sectors, key=lambda s: s.get("composite") or 0, reverse=True)

    for s in sorted_sectors:
        marker = " ***" if s in interesting else ""
        stealth = " [STEALTH]" if s.get("stealth_accumulation") else ""
        breadth = s.get("breadth_pct")
        breadth_str = f"{breadth:.0f}%" if breadth is not None else "N/A"
        print(
            f"  {s['etf']:5s} {s['name']:20s} "
            f"Quad={s['quadrant']:11s} "
            f"Comp={s.get('composite', 'N/A'):>5} "
            f"RS={s['rs_ratio']:6.1f} "
            f"Accel={s['acceleration']:+6.1f} "
            f"CMF={s['cmf']:+.3f} "
            f"Breadth={breadth_str:>4}"
            f"{stealth}{marker}"
        )

    print(f"\n  {len(interesting)} of {len(sectors)} sectors qualify")
    print("=" * 70)


def print_stock_results(passed: List[Dict], rejected: List[Dict], verbose: bool = False):
    """Print stock results to console."""
    print("\n" + "-" * 70)
    print("STOCK PICKS")
    print("-" * 70)

    # Sort by conviction then RS accel
    conv_order = {"HIGH": 0, "MEDIUM": 1, "WATCH": 2}
    sorted_stocks = sorted(passed, key=lambda s: (conv_order.get(s.get("conviction", "WATCH"), 3), -s["rs_accel"]))

    for s in sorted_stocks:
        inst_str = f"{s['institutional_pct']:.0f}%" if s.get("institutional_pct") is not None else "N/A"
        print(
            f"  [{s['conviction']:6s}] {s['symbol']:6s} "
            f"{s['sector_name']:18s} "
            f"{s['category']:11s} {s['phase']:15s} "
            f"RS_Accel={s['rs_accel']:+6.2f} "
            f"Vol={s['vol_ratio']:.1f}x "
            f"Inst={inst_str:>4} "
            f"${s['price']:.2f}"
        )

    print(f"\n  {len(passed)} passed, {len(rejected)} rejected")

    if verbose and rejected:
        print("\n  Rejected:")
        for s in rejected[:10]:
            reasons = ", ".join(s.get("rejection_reasons", []))
            print(f"    {s['symbol']:6s} {s['sector_name']:18s} -> {reasons}")
        if len(rejected) > 10:
            print(f"    ... and {len(rejected) - 10} more")

    print("-" * 70)


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run_scan(
    sector_filter: Optional[List[str]] = None,
    dry_run: bool = False,
    verbose: bool = False,
    force_refresh: bool = False,
    min_conviction: str = "WATCH",
    return_full: bool = False,
) -> Dict:
    """Run the full rotation scan pipeline.

    Args:
        return_full: If True, include all intermediate data in the return dict
            (all_sectors, interesting, passed_stocks, rejected_stocks, scan_date)
            for use by the HTML report generator.

    Returns:
        Summary dict with sectors_analyzed, stocks_passed, alerts_sent.
        If return_full=True, also includes full intermediate data.
    """
    _ensure_dirs()

    if verbose:
        logging.getLogger("rotation_scanner").setLevel(logging.DEBUG)

    # Step 1: Fetch ETF data and analyze sectors
    log.info("Step 1: Fetching ETF data...")
    etf_df = fetch_etf_data(force_refresh=force_refresh)
    scan_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    if etf_df is None:
        log.error("Cannot proceed without ETF data")
        result = {"sectors_analyzed": 0, "stocks_passed": 0, "alerts_sent": 0}
        if return_full:
            result.update(all_sectors=[], interesting=[], passed_stocks=[],
                          rejected_stocks=[], scan_date=scan_date)
        return result

    sectors = analyze_all_sectors(etf_df)
    log.info("Analyzed %d sectors", len(sectors))

    # Compute initial composite (breadth/smart_money not yet available)
    for s in sectors:
        s["composite"] = compute_composite(s)

    # Step 2: Filter interesting sectors
    if sector_filter:
        sector_filter_upper = [s.upper() for s in sector_filter]
        sectors_to_process = [s for s in sectors if s["etf"] in sector_filter_upper]
        if not sectors_to_process:
            log.warning("No matching sectors found for filter: %s", sector_filter)
            result = {"sectors_analyzed": 0, "stocks_passed": 0, "alerts_sent": 0}
            if return_full:
                result.update(all_sectors=sectors, interesting=[], passed_stocks=[],
                              rejected_stocks=[], scan_date=scan_date)
            return result
        interesting = sectors_to_process  # bypass filter when explicitly requested
    else:
        interesting = filter_interesting_sectors(sectors)

    log.info("Step 2: %d interesting sectors", len(interesting))

    # Step 3: Map to stocks
    sector_stocks = get_candidate_stocks(interesting)
    total_candidates = sum(len(v) for v in sector_stocks.values())
    log.info("Step 3: %d candidate stocks across %d sectors", total_candidates, len(sector_stocks))

    if total_candidates == 0:
        print_sector_summary(sectors, interesting)
        result = {"sectors_analyzed": len(sectors), "stocks_passed": 0, "alerts_sent": 0}
        if return_full:
            result.update(all_sectors=sectors, interesting=interesting, passed_stocks=[],
                          rejected_stocks=[], scan_date=scan_date)
        return result

    # Step 4: Enrich stocks
    log.info("Step 4: Enriching stocks...")
    enriched = enrich_stocks(sector_stocks, etf_df, sectors, force_refresh=force_refresh)
    log.info("Enriched %d stocks", len(enriched))

    # Print sector summary (now with breadth updated)
    print_sector_summary(sectors, interesting)

    # Step 5: Quality gates
    passed, rejected = apply_quality_gates(enriched)
    log.info("Step 5: %d passed quality gates, %d rejected", len(passed), len(rejected))

    # Step 6: Classify
    for s in passed:
        classify_stock(s)

    # Filter out AVOID category
    passed = [s for s in passed if s["category"] != "AVOID"]

    # Step 7: Score conviction
    for s in passed:
        score_conviction(s)

    # Apply min conviction filter
    conv_order = {"WATCH": 0, "MEDIUM": 1, "HIGH": 2}
    min_level = conv_order.get(min_conviction, 0)
    passed = [s for s in passed if conv_order.get(s["conviction"], 0) >= min_level]

    print_stock_results(passed, rejected, verbose=verbose)

    # Step 8: Dedup and alert
    state = _load_state()
    clean_state(state)

    notifier = get_notifier()
    alerts_sent = 0

    # Build sector -> stocks mapping for alerts
    sector_stock_map = {}
    for s in passed:
        sector_stock_map.setdefault(s["etf"], []).append(s)

    for sector in interesting:
        etf = sector["etf"]
        stocks = sector_stock_map.get(etf, [])
        if not stocks:
            continue

        # Send sector summary
        sector_msg = format_sector_alert(sector, stocks)
        if dry_run:
            print(f"\n[TELEGRAM] {sector_msg}")
        else:
            notifier.send(sector_msg)

        # Send individual stock alerts (HIGH and MEDIUM only for Telegram)
        for s in stocks:
            if s["conviction"] == "WATCH":
                continue

            if not should_alert(s["symbol"], s["conviction"], s["category"], s["phase"], state):
                log.info("Dedup: skipping %s (already alerted)", s["symbol"])
                continue

            stock_msg = format_stock_alert(s)
            if dry_run:
                print(f"\n[TELEGRAM] {stock_msg}")
            else:
                ok = notifier.send(stock_msg)
                if ok:
                    alerts_sent += 1
                    record_alert(s["symbol"], s["conviction"], s["category"], s["phase"], state)
                    time.sleep(0.5)  # rate limit

    if not dry_run:
        _save_state(state)

    summary = {
        "sectors_analyzed": len(sectors),
        "interesting_sectors": len(interesting),
        "stocks_enriched": len(enriched),
        "stocks_passed": len(passed),
        "alerts_sent": alerts_sent,
    }

    print(f"\nSummary: {summary}")

    if return_full:
        summary.update(
            all_sectors=sectors,
            interesting=interesting,
            passed_stocks=passed,
            rejected_stocks=rejected,
            scan_date=scan_date,
        )

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sector Rotation Scanner")
    parser.add_argument("--dry-run", action="store_true", help="Print only, no Telegram")
    parser.add_argument("--sector", type=str, default=None,
                        help="Comma-separated sector ETFs to scan (e.g. SMH,XLF)")
    parser.add_argument("--verbose", action="store_true", help="Detailed logging")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass daily cache")
    parser.add_argument("--min-conviction", type=str, default="WATCH",
                        choices=["WATCH", "MEDIUM", "HIGH"],
                        help="Minimum conviction level for output")
    parser.add_argument("--html", action="store_true",
                        help="Generate HTML dashboard report")
    parser.add_argument("--supabase", action="store_true",
                        help="Push results to Supabase for web dashboard")

    args = parser.parse_args()

    sector_filter = None
    if args.sector:
        sector_filter = [s.strip() for s in args.sector.split(",")]

    result = run_scan(
        sector_filter=sector_filter,
        dry_run=args.dry_run,
        verbose=args.verbose,
        force_refresh=args.force_refresh,
        min_conviction=args.min_conviction,
        return_full=args.html or args.supabase,
    )

    if args.supabase:
        from runners.rotation_supabase import push_to_supabase
        push_to_supabase(result)

    if args.html:
        from runners.rotation_report import write_report
        output = str(_DATA_DIR / "report.html")
        path = write_report(result, output)
        print(f"\nHTML report: {path}")


if __name__ == "__main__":
    main()
