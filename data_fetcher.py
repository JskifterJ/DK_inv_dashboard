"""
╔══════════════════════════════════════════════════════════════════════╗
║           DATA FETCHER  —  Live & Illiquid Asset Prices             ║
║           data_fetcher.py                                           ║
╠══════════════════════════════════════════════════════════════════════╣
║  Handles:                                                           ║
║  • yfinance  — equities, ETFs, bonds (live market data)            ║
║  • Manual overrides  — illiquid assets (PE, real estate, alts)     ║
║  • Copenhagen property index proxy                                  ║
║  • Graceful fallback when internet is unavailable                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Optional
import warnings
warnings.filterwarnings("ignore")

# Try importing yfinance; handle gracefully if not installed
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# ══════════════════════════════════════════════════════════════════════
#  SECTION 1 — POPULAR DANISH-INVESTOR TICKERS
#  ─────────────────────────────────────────────────────────────────────
#  Pre-populated list of commonly held assets for the portfolio picker.
# ══════════════════════════════════════════════════════════════════════

POPULAR_TICKERS = {
    # ── Broad-Market ETFs (accumulating, USD/EUR) ─────────────────────
    "EUNL.DE":  "iShares MSCI World (EUR, Lager*)",
    "SXR8.DE":  "iShares Core S&P 500 (EUR, Lager*)",
    "VWCE.DE":  "Vanguard FTSE All-World (EUR, Lager*)",
    "IEMG":     "iShares Core EM (USD)",
    # ── Danish Stocks ─────────────────────────────────────────────────
    "NOVO-B.CO": "Novo Nordisk B (CPH)",
    "DSV.CO":    "DSV A/S (CPH)",
    "MAERSK-B.CO": "A.P. Møller-Mærsk B (CPH)",
    "ORSTED.CO": "Ørsted A/S (CPH)",
    # ── Global Tech ───────────────────────────────────────────────────
    "MSFT":     "Microsoft",
    "AAPL":     "Apple",
    "NVDA":     "NVIDIA",
    # ── Bonds ─────────────────────────────────────────────────────────
    "TLT":      "iShares 20+ Year Treasury Bond ETF",
    "AGGG.L":   "iShares Core Global Aggregate Bond ETF (GBP)",
    # ── Real Assets / Alternatives ────────────────────────────────────
    "GLD":      "SPDR Gold Shares",
    "BTC-USD":  "Bitcoin (USD)",
}
# * These ETFs are typically subject to lagerbeskatning for Danish investors.
#   Always verify your specific ETF's tax treatment with SKAT.dk.


# ══════════════════════════════════════════════════════════════════════
#  SECTION 2 — LIVE DATA FETCHER
# ══════════════════════════════════════════════════════════════════════

def fetch_current_price(ticker: str) -> dict:
    """
    Fetch the latest price and basic info for a single ticker via yfinance.

    Falls back to a placeholder if network is unavailable.

    Parameters
    ----------
    ticker : Yahoo Finance ticker symbol (e.g. "EUNL.DE", "NOVO-B.CO").

    Returns
    -------
    dict with keys: ticker, price, currency, name, change_pct, last_updated
    """
    if not YFINANCE_AVAILABLE:
        return _placeholder_price(ticker, reason="yfinance not installed")

    try:
        tkr  = yf.Ticker(ticker)
        info = tkr.info

        # yfinance returns price under different keys depending on asset type
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")
            or info.get("previousClose")
            or 0.0
        )
        prev_close   = info.get("previousClose") or price
        change_pct   = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
        currency     = info.get("currency", "USD")
        name         = info.get("longName") or info.get("shortName") or ticker

        return {
            "ticker":       ticker,
            "price":        round(float(price), 4),
            "currency":     currency,
            "name":         name,
            "change_pct":   round(change_pct, 2),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "error":        None,
        }
    except Exception as e:
        return _placeholder_price(ticker, reason=str(e))


def fetch_historical(
    ticker:     str,
    period:     str  = "5y",
    interval:   str  = "1mo",
) -> pd.DataFrame:
    """
    Fetch monthly historical OHLCV data for a ticker.

    Parameters
    ----------
    ticker   : Yahoo Finance ticker symbol.
    period   : "1y", "2y", "5y", "10y", "max"
    interval : "1d", "1wk", "1mo"

    Returns
    -------
    DataFrame with columns: Date, Open, High, Low, Close, Volume, Return
    An empty DataFrame is returned on error.
    """
    if not YFINANCE_AVAILABLE:
        return _placeholder_history(ticker)

    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return _placeholder_history(ticker)

        df = df.reset_index()
        # Flatten multi-level columns if yfinance returns them
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [" ".join(col).strip() for col in df.columns.values]
            # Rename to standard names
            df.columns = [c.split(" ")[0] for c in df.columns]

        df = df.rename(columns={"Datetime": "Date", "date": "Date"})
        df["Date"]   = pd.to_datetime(df["Date"])
        df["Return"] = df["Close"].pct_change()
        df["ticker"] = ticker
        return df[["Date", "Close", "Return", "ticker"]].dropna()

    except Exception:
        return _placeholder_history(ticker)


def fetch_portfolio_snapshot(positions: list[dict]) -> pd.DataFrame:
    """
    Fetch current prices for a list of portfolio positions and compute
    market values.

    Parameters
    ----------
    positions : List of dicts, each with keys:
        - ticker       : str   (e.g. "EUNL.DE")
        - quantity     : float (number of units held)
        - cost_basis   : float (total amount paid in DKK)
        - asset_type   : str   ("etf", "stock", "bond", "crypto")
        - tax_vehicle  : str   ("private_realisation", "private_lager",
                                "ask", "holding")
        - currency     : str   (optional override; e.g. "DKK", "USD", "EUR")

    Returns
    -------
    DataFrame with current values, P&L, and tax treatment labels.
    """
    records = []
    fx_cache = {}  # Cache FX rates to avoid repeated lookups

    for pos in positions:
        ticker     = pos.get("ticker", "")
        quantity   = float(pos.get("quantity", 0))
        cost_basis = float(pos.get("cost_basis", 0))
        asset_type = pos.get("asset_type", "stock")
        vehicle    = pos.get("tax_vehicle", "private_realisation")

        price_info = fetch_current_price(ticker)
        price      = price_info["price"]
        currency   = price_info["currency"]

        # Simple FX conversion to DKK (approximate)
        fx_rate = _get_fx_to_dkk(currency, fx_cache)

        market_value_local = price * quantity
        market_value_dkk   = market_value_local * fx_rate
        unrealised_pnl_dkk = market_value_dkk - cost_basis
        pnl_pct            = (unrealised_pnl_dkk / cost_basis * 100) if cost_basis else 0

        records.append({
            "Ticker":           ticker,
            "Name":             price_info.get("name", ticker),
            "Asset Type":       asset_type,
            "Tax Vehicle":      vehicle,
            "Quantity":         quantity,
            "Price (local)":    price,
            "Currency":         currency,
            "FX → DKK":        round(fx_rate, 4),
            "Market Value DKK": round(market_value_dkk, 0),
            "Cost Basis DKK":   round(cost_basis, 0),
            "Unrealised P&L":   round(unrealised_pnl_dkk, 0),
            "P&L %":            round(pnl_pct, 2),
            "Last Updated":     price_info.get("last_updated", "N/A"),
            "Price Error":      price_info.get("error"),
        })

    return pd.DataFrame(records)


# ══════════════════════════════════════════════════════════════════════
#  SECTION 3 — ILLIQUID ASSET PROXIES
# ══════════════════════════════════════════════════════════════════════

def estimate_property_value(
    purchase_price:     float,
    purchase_year:      int,
    property_type:      str  = "copenhagen_apartment",
    annual_override:    Optional[float] = None,
) -> dict:
    """
    Estimate current real estate value using a simplified index proxy.

    In production you would link to Boligsiden.dk / Statistics Denmark data.
    Here we use approximate historic average appreciation rates.

    Parameters
    ----------
    purchase_price  : Original purchase price (DKK).
    purchase_year   : Year of purchase.
    property_type   : One of: "copenhagen_apartment", "copenhagen_house",
                               "provincial_house", "summer_house"
    annual_override : If provided, use this rate instead of the regional default.

    Returns
    -------
    dict with estimated current value and cumulative appreciation.
    """
    # Approximate long-run annual real appreciation (nominal, post-GFC average)
    APPRECIATION_RATES = {
        "copenhagen_apartment": 0.055,   # ~5.5 %/yr post-GFC
        "copenhagen_house":     0.045,
        "provincial_house":     0.025,
        "summer_house":         0.035,
    }

    rate     = annual_override or APPRECIATION_RATES.get(property_type, 0.035)
    years    = date.today().year - purchase_year
    current  = purchase_price * ((1 + rate) ** years)
    gain     = current - purchase_price

    return {
        "purchase_price":       purchase_price,
        "purchase_year":        purchase_year,
        "estimated_value_dkk":  round(current, 0),
        "estimated_gain_dkk":   round(gain, 0),
        "appreciation_rate":    rate,
        "years_held":           years,
        "property_type":        property_type,
        "tax_on_gain":          0.0,      # Parcelhusreglen — tax-free for primary home
        "note": (
            "Estimate only. Based on regional average appreciation. "
            "Verify with Boligsiden.dk or a certified ejendomsmægler."
        ),
    }


def estimate_private_equity_value(
    initial_investment: float,
    investment_year:    int,
    fund_name:          str  = "EQT Nexus",
    irr_assumption:     float = 0.12,    # 12 % net IRR is typical for Nordic PE
    management_fee:     float = 0.02,    # 2 % annual management fee
) -> dict:
    """
    Estimate current NAV for a private equity / PE fund position.

    Small-ticket PE funds (like EQT Nexus, CapMan, etc.) report NAV quarterly.
    This proxy uses a simple IRR model until official NAV data is available.

    Parameters
    ----------
    initial_investment : Amount invested (DKK or EUR — keep consistent).
    investment_year    : Year of first close / investment.
    fund_name          : Name label for the fund.
    irr_assumption     : Net IRR assumption after fund fees.
    management_fee     : Annual management fee (reduces effective return).
    """
    years    = date.today().year - investment_year
    net_irr  = irr_assumption - management_fee
    nav      = initial_investment * ((1 + net_irr) ** years)
    gain     = nav - initial_investment

    return {
        "fund":                 fund_name,
        "initial_investment":   initial_investment,
        "investment_year":      investment_year,
        "years_held":           years,
        "assumed_net_irr":      net_irr,
        "estimated_nav":        round(nav, 0),
        "estimated_gain":       round(gain, 0),
        "liquidity":            "Illiquid — no market price available",
        "tax_treatment":        "Aktieindkomst on exit (realisationsbeskatning)",
        "note": (
            "IRR proxy only. Actual NAV should be obtained from fund statements. "
            "EQT Nexus and similar retail PE funds report quarterly NAV."
        ),
    }


def estimate_alternative_asset(
    asset_name:       str,
    purchase_price:   float,
    purchase_year:    int,
    asset_class:      str = "watch",
) -> dict:
    """
    Estimate current value for illiquid alternatives (watches, classic cars, art).

    Parameters
    ----------
    asset_name     : Descriptive name (e.g. "Rolex Daytona Ref. 116500").
    purchase_price : Purchase price (DKK).
    purchase_year  : Year purchased.
    asset_class    : "watch", "classic_car", "art", "wine"
    """
    # Approximate annual appreciation — highly variable; these are illustrative
    ALT_APPRECIATION = {
        "watch":       0.07,   # Luxury watch market (post-2020 boom normalised)
        "classic_car": 0.06,
        "art":         0.05,
        "wine":        0.08,
    }
    rate   = ALT_APPRECIATION.get(asset_class, 0.05)
    years  = date.today().year - purchase_year
    value  = purchase_price * ((1 + rate) ** years)
    gain   = value - purchase_price

    return {
        "asset_name":     asset_name,
        "asset_class":    asset_class,
        "purchase_price": purchase_price,
        "purchase_year":  purchase_year,
        "est_value_dkk":  round(value, 0),
        "est_gain_dkk":   round(gain, 0),
        "rate":           rate,
        "tax_treatment":  "Kapitalindkomst on sale (non-hobby assets)",
        "note":           "Highly speculative estimate. Values from market research only.",
    }


# ══════════════════════════════════════════════════════════════════════
#  SECTION 4 — FX UTILITIES
# ══════════════════════════════════════════════════════════════════════

# Approximate fixed fallback FX rates (DKK per 1 unit of foreign currency)
# Update periodically or fetch live via yfinance if needed.
FX_FALLBACK_RATES = {
    "DKK": 1.00,
    "EUR": 7.46,
    "USD": 6.90,
    "GBP": 8.75,
    "SEK": 0.63,
    "NOK": 0.63,
    "CHF": 7.70,
    "JPY": 0.046,
}


def _get_fx_to_dkk(currency: str, cache: dict) -> float:
    """
    Return the DKK exchange rate for a given currency.
    Uses yfinance if available; falls back to hardcoded approximations.
    """
    if currency in cache:
        return cache[currency]

    if currency == "DKK":
        cache["DKK"] = 1.0
        return 1.0

    if YFINANCE_AVAILABLE:
        try:
            fx_ticker = f"{currency}DKK=X"
            rate_info = fetch_current_price(fx_ticker)
            if rate_info["price"] and rate_info["price"] > 0:
                cache[currency] = rate_info["price"]
                return rate_info["price"]
        except Exception:
            pass

    # Fallback to hardcoded rates
    rate = FX_FALLBACK_RATES.get(currency, 7.0)
    cache[currency] = rate
    return rate


# ══════════════════════════════════════════════════════════════════════
#  SECTION 5 — PLACEHOLDER GENERATORS  (offline / error fallback)
# ══════════════════════════════════════════════════════════════════════

def _placeholder_price(ticker: str, reason: str = "offline") -> dict:
    """Return a safe placeholder when live data is unavailable."""
    return {
        "ticker":       ticker,
        "price":        0.0,
        "currency":     "N/A",
        "name":         ticker,
        "change_pct":   0.0,
        "last_updated": "OFFLINE",
        "error":        reason,
    }


def _placeholder_history(ticker: str) -> pd.DataFrame:
    """Return an empty history DataFrame when live data is unavailable."""
    return pd.DataFrame(columns=["Date", "Close", "Return", "ticker"])


# ══════════════════════════════════════════════════════════════════════
#  SECTION 6 — SAMPLE PORTFOLIO BUILDER  (demo / onboarding)
# ══════════════════════════════════════════════════════════════════════

def build_sample_portfolio() -> list[dict]:
    """
    Returns a sample portfolio for demo / first-run mode.
    Users replace this with their own holdings in the UI.
    """
    return [
        # ── ASK ───────────────────────────────────────────────────────
        {
            "ticker":      "SXR8.DE",
            "quantity":    50,
            "cost_basis":  80_000,
            "asset_type":  "etf",
            "tax_vehicle": "ask",
        },
        # ── Private ETF ───────────────────────────────────────────────
        {
            "ticker":      "EUNL.DE",
            "quantity":    200,
            "cost_basis":  350_000,
            "asset_type":  "etf",
            "tax_vehicle": "private_lager",
        },
        # ── Individual stocks (realisationsbeskatning) ────────────────
        {
            "ticker":      "NOVO-B.CO",
            "quantity":    500,
            "cost_basis":  250_000,
            "asset_type":  "stock",
            "tax_vehicle": "private_realisation",
        },
        {
            "ticker":      "MSFT",
            "quantity":    30,
            "cost_basis":  120_000,
            "asset_type":  "stock",
            "tax_vehicle": "private_realisation",
        },
    ]


def build_sample_illiquid_assets() -> dict:
    """
    Returns sample illiquid assets for demo mode.
    """
    return {
        "real_estate": [
            estimate_property_value(
                purchase_price=3_500_000,
                purchase_year=2015,
                property_type="copenhagen_apartment",
            )
        ],
        "private_equity": [
            estimate_private_equity_value(
                initial_investment=500_000,
                investment_year=2021,
                fund_name="EQT Nexus",
                irr_assumption=0.12,
            )
        ],
        "alternatives": [
            estimate_alternative_asset(
                asset_name="Rolex Submariner",
                purchase_price=85_000,
                purchase_year=2019,
                asset_class="watch",
            ),
        ],
    }
