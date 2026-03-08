"""
╔══════════════════════════════════════════════════════════════════════╗
║     DANSK INVESTERINGS DASHBOARD & SCENARIO SIMULATOR               ║
║     app.py  —  Main Streamlit Application                           ║
╠══════════════════════════════════════════════════════════════════════╣
║  Run with:  streamlit run app.py                                    ║
║                                                                     ║
║  Requires:  pip install streamlit pandas numpy plotly yfinance      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import date

# ── Local modules ─────────────────────────────────────────────────────
from tax_engine import (
    DanishTaxEngine,
    ASK_DEPOSIT_LIMIT,
    AKTIEINDKOMST_LOW_RATE,
    AKTIEINDKOMST_HIGH_RATE,
    AKTIEINDKOMST_THRESHOLD_SINGLE,
    AKTIEINDKOMST_THRESHOLD_MARRIED,
    CORPORATE_TAX_RATE,
    ASK_TAX_RATE,
    KAPITALINDKOMST_POS_RATE,
    RENTEFRADRAG_TAX_VALUE,
    HOLDING_DEFAULT_ADMIN_COST,
)
from data_fetcher import (
    fetch_portfolio_snapshot,
    fetch_current_price,
    fetch_historical,
    build_sample_portfolio,
    build_sample_illiquid_assets,
    estimate_property_value,
    estimate_private_equity_value,
    estimate_alternative_asset,
    POPULAR_TICKERS,
)


# ══════════════════════════════════════════════════════════════════════
#  PAGE CONFIGURATION  — must be the FIRST streamlit call
# ══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title  = "Dansk Investerings Dashboard",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)


# ══════════════════════════════════════════════════════════════════════
#  GLOBAL COLOUR PALETTE  (consistent across all charts)
# ══════════════════════════════════════════════════════════════════════

COLOURS = {
    "Private Stocks\n(Realisationsbeskatning)": "#2196F3",   # Blue
    "Private ETF\n(Lagerbeskatning 27/42%)":    "#FF5722",   # Orange-red
    "ASK\n(Lagerbeskatning 17%)":               "#4CAF50",   # Green
    "Holding ApS\n(22% + Udbytteskat)":         "#9C27B0",   # Purple
    "No Tax (Benchmark)":                        "#9E9E9E",   # Grey
}


# ══════════════════════════════════════════════════════════════════════
#  FORMATTING HELPERS
# ══════════════════════════════════════════════════════════════════════

def fmt_dkk(amount: float) -> str:
    """Format a number as DKK with thousands separator."""
    if abs(amount) >= 1_000_000:
        return f"{amount/1_000_000:.2f}M DKK"
    elif abs(amount) >= 1_000:
        return f"{amount:,.0f} DKK"
    else:
        return f"{amount:.0f} DKK"


def fmt_pct(rate: float) -> str:
    """Format a decimal as a percentage string."""
    return f"{rate*100:.1f} %"


def household_ask_cap(married: bool) -> float:
    """Return ASK cap for household: single = 1x, household/two adults = 2x."""
    return ASK_DEPOSIT_LIMIT * (2 if married else 1)


def _normalize_int_input_key(key: str, min_value: int, max_value: int, step: int) -> None:
    """Normalize a text input to a clamped, comma-formatted integer."""
    raw = str(st.session_state.get(key, "0"))
    cleaned = raw.replace(",", "").replace(" ", "").strip()

    if cleaned in {"", "-"}:
        parsed = min_value
    else:
        try:
            parsed = int(float(cleaned))
        except ValueError:
            parsed = min_value

    parsed = max(min_value, min(max_value, parsed))
    if step > 1:
        parsed = int(round(parsed / step) * step)
        parsed = max(min_value, min(max_value, parsed))

    st.session_state[key] = f"{parsed:,}"


def int_input_with_commas(
    label: str,
    key: str,
    min_value: int,
    max_value: int,
    value: int,
    step: int = 1,
    help: str = None,
    disabled: bool = False,
) -> int:
    """Render an integer input with visible thousands separators."""
    if key not in st.session_state:
        v0 = max(min_value, min(max_value, int(value)))
        st.session_state[key] = f"{v0:,}"

    st.text_input(
        label,
        key=key,
        help=help,
        disabled=disabled,
        on_change=_normalize_int_input_key,
        args=(key, min_value, max_value, step),
    )

    raw = str(st.session_state.get(key, "0"))
    cleaned = raw.replace(",", "").replace(" ", "").strip()
    if cleaned in {"", "-"}:
        return min_value
    try:
        parsed = int(float(cleaned))
    except ValueError:
        return min_value
    parsed = max(min_value, min(max_value, parsed))
    if step > 1:
        parsed = int(round(parsed / step) * step)
    return parsed


def _normalize_float_input_key(key: str, min_value: float, max_value: float, decimals: int) -> None:
    """Normalize a text input to a clamped, comma-formatted float."""
    raw = str(st.session_state.get(key, "0"))
    cleaned = raw.replace(",", "").replace(" ", "").strip()

    if cleaned in {"", "-", ".", "-."}:
        parsed = min_value
    else:
        try:
            parsed = float(cleaned)
        except ValueError:
            parsed = min_value

    parsed = max(min_value, min(max_value, parsed))
    st.session_state[key] = f"{parsed:,.{decimals}f}"


def float_input_with_commas(
    label: str,
    key: str,
    min_value: float,
    max_value: float,
    value: float,
    decimals: int = 2,
    help: str = None,
    disabled: bool = False,
) -> float:
    """Render a float input with visible thousands separators."""
    if key not in st.session_state:
        v0 = max(min_value, min(max_value, float(value)))
        st.session_state[key] = f"{v0:,.{decimals}f}"

    st.text_input(
        label,
        key=key,
        help=help,
        disabled=disabled,
        on_change=_normalize_float_input_key,
        args=(key, min_value, max_value, decimals),
    )

    raw = str(st.session_state.get(key, "0"))
    cleaned = raw.replace(",", "").replace(" ", "").strip()
    if cleaned in {"", "-", ".", "-."}:
        return min_value
    try:
        parsed = float(cleaned)
    except ValueError:
        return min_value
    return max(min_value, min(max_value, parsed))


def hex_to_rgba(hex_color: str, alpha: float = 0.2) -> str:
    """Convert #RRGGBB hex to Plotly-compatible rgba(r,g,b,a)."""
    clean = hex_color.lstrip("#")
    if len(clean) != 6:
        return f"rgba(96,125,139,{alpha})"
    r = int(clean[0:2], 16)
    g = int(clean[2:4], 16)
    b = int(clean[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def city_profile(city: str) -> dict:
    """Location presets for living costs and property-tax assumptions."""
    profiles = {
        "København": {
            "municipal_tax": 0.248,
            "monthly_living": 32_000,
            "property_tax_rate": 0.0092,
            "property_maintenance_rate": 0.010,
            "car_depreciation": 55_000,
            "heloc_rate": 0.045,
        },
        "Aarhus": {
            "municipal_tax": 0.246,
            "monthly_living": 28_000,
            "property_tax_rate": 0.0086,
            "property_maintenance_rate": 0.009,
            "car_depreciation": 45_000,
            "heloc_rate": 0.043,
        },
        "Anden kommune": {
            "municipal_tax": 0.240,
            "monthly_living": 24_000,
            "property_tax_rate": 0.0078,
            "property_maintenance_rate": 0.008,
            "car_depreciation": 38_000,
            "heloc_rate": 0.041,
        },
    }
    return profiles.get(city, profiles["Anden kommune"])


def suggested_portfolio_mix(annual_income: float, married: bool) -> dict:
    """Tax-aware default weights; ASK is always prioritized up to cap."""
    high_income_cutoff = 900_000 if not married else 1_300_000
    if annual_income >= high_income_cutoff:
        return {
            "ask": 0.25,
            "private_etf": 0.20,
            "private_equity": 0.20,
            "holding": 0.25,
            "bonds": 0.10,
        }
    return {
        "ask": 0.30,
        "private_etf": 0.30,
        "private_equity": 0.20,
        "holding": 0.10,
        "bonds": 0.10,
    }


def normalize_weights(weights: dict) -> dict:
    """Normalize arbitrary non-negative weights to 100%."""
    clean = {k: max(0.0, float(v)) for k, v in weights.items()}
    total = sum(clean.values())
    if total <= 0:
        even = 1.0 / len(clean)
        return {k: even for k in clean}
    return {k: v / total for k, v in clean.items()}


def allocate_with_ask_cap(amount: float, weights: dict, ask_used: float, ask_cap: float = ASK_DEPOSIT_LIMIT) -> tuple[dict, float]:
    """Allocate amount by weights while filling ASK first until the legal cap."""
    alloc = {k: 0.0 for k in weights}
    remaining = max(0.0, amount)
    ask_room = max(0.0, ask_cap - ask_used)

    ask_top_up = min(remaining, ask_room)
    alloc["ask"] += ask_top_up
    ask_used += ask_top_up
    remaining -= ask_top_up

    if remaining <= 0:
        return alloc, ask_used

    non_ask = {k: v for k, v in weights.items() if k != "ask"}
    non_ask = normalize_weights(non_ask)
    for key, w in non_ask.items():
        alloc[key] += remaining * w

    return alloc, ask_used


def macro_regime_presets() -> dict:
    """Preset macro assumptions for deterministic and stochastic scenario analysis."""
    return {
        "Base": {
            "salary_growth": 0.025,
            "inflation": 0.020,
            "return_shift": 0.000,
            "rate_shift": 0.000,
            "house_shift": 0.000,
            "vol_multiplier": 1.00,
        },
        "Bull": {
            "salary_growth": 0.032,
            "inflation": 0.022,
            "return_shift": 0.018,
            "rate_shift": -0.004,
            "house_shift": 0.010,
            "vol_multiplier": 0.85,
        },
        "Bear": {
            "salary_growth": 0.010,
            "inflation": 0.030,
            "return_shift": -0.030,
            "rate_shift": 0.010,
            "house_shift": -0.010,
            "vol_multiplier": 1.35,
        },
    }


def glidepath_weights(base_weights: dict, year: int, years: int, max_shift_to_bonds: float) -> dict:
    """Shift risk assets gradually into bonds through the investment horizon."""
    weights = normalize_weights(base_weights)
    if years <= 1 or max_shift_to_bonds <= 0:
        return weights

    progress = min(1.0, max(0.0, (year - 1) / (years - 1)))
    shift = max_shift_to_bonds * progress

    risky_keys = ["ask", "private_etf", "private_equity", "holding"]
    risky_total = sum(weights.get(k, 0.0) for k in risky_keys)
    if risky_total <= 0:
        return weights

    moved = risky_total * shift
    new_weights = weights.copy()
    for k in risky_keys:
        new_weights[k] = weights[k] * (1 - shift)
    new_weights["bonds"] = weights.get("bonds", 0.0) + moved
    return normalize_weights(new_weights)


def assumptions_health_check(
    annual_salary: float,
    annual_living_cost: float,
    annual_household_fixed: float,
    annual_car_depreciation: float,
    effective_income_tax: float,
    returns: dict,
    ltv: int,
    mortgage_rate: float,
) -> tuple[int, list]:
    """Return a confidence score and warnings for assumption realism."""
    score = 100
    warnings = []

    baseline_spend = annual_living_cost + annual_household_fixed + annual_car_depreciation
    if annual_salary * (1 - effective_income_tax) < baseline_spend:
        warnings.append("Efter-skat indkomst dækker ikke de faste basisudgifter i base case.")
        score -= 20

    if max(returns.values()) > 0.12:
        warnings.append("Mindst én afkastantagelse er over 12 % p.a.; høj optimismetrisiko.")
        score -= 12

    if returns.get("bonds", 0) > returns.get("private_etf", 0):
        warnings.append("Obligationsafkast er sat højere end ETF-afkast; kontrollér antagelser.")
        score -= 8

    if ltv >= 70 and mortgage_rate >= 0.05:
        warnings.append("Høj LTV kombineret med høj rente øger refinansierings- og tvangsrisiko.")
        score -= 12

    if effective_income_tax < 0.25 or effective_income_tax > 0.58:
        warnings.append("Effektiv indkomstskat ligger uden for typisk dansk interval for de fleste husholdninger.")
        score -= 8

    return max(0, score), warnings


def estimate_effective_income_tax(annual_income: float, municipal_tax: float, married: bool = False) -> float:
    """Approximate Danish effective income tax using bracket mechanics."""
    income = max(0.0, annual_income)

    # AM-bidrag (8 %) is applied on gross labor income.
    am_tax = income * 0.08
    taxable_after_am = income - am_tax

    # Bund + kommune on taxable labor income.
    bund_rate = 0.1209
    base_tax = taxable_after_am * (bund_rate + municipal_tax)

    # Simplified topskat threshold (after AM). Married households get a wider buffer.
    topskat_threshold = 640_000 * (1.7 if married else 1.0)
    topskat_rate = 0.15
    topskat_tax = max(0.0, taxable_after_am - topskat_threshold) * topskat_rate

    total_tax = am_tax + base_tax + topskat_tax
    return min(0.70, total_tax / income) if income > 0 else 0.0


def expected_post_tax_return_for_vehicle(
    engine: DanishTaxEngine,
    gross_return: float,
    vehicle: str,
    invested_amount: float,
    ask_room: float,
) -> tuple[float, str]:
    """Estimate post-tax expected return for gearing guidance by destination vehicle."""
    amount = max(1.0, invested_amount)
    r = gross_return

    if vehicle == "ask":
        if ask_room <= 0:
            return r * (1 - ASK_TAX_RATE), "ASK er fyldt; sats anvendt kun som reference."
        return r * (1 - ASK_TAX_RATE), "ASK lagerbeskattes med 17 %."

    if vehicle == "private_etf":
        gain = amount * r
        tax = engine.aktieindkomst_tax(max(0.0, gain)).tax_paid if gain > 0 else 0.0
        return (gain - tax) / amount, "ETF antaget lagerbeskattet via aktieindkomstsatser."

    if vehicle == "private_equity":
        div_yield = 0.02
        dividend = amount * div_yield
        appreciation = amount * max(-1.0, (r - div_yield))
        div_tax = engine.aktieindkomst_tax(max(0.0, dividend)).tax_paid if dividend > 0 else 0.0
        post = (appreciation + dividend - div_tax) / amount
        return post, "Realisationsaktier: kun udbytte beskattes løbende (forenklet)."

    if vehicle == "holding":
        gain = amount * r
        tax = max(0.0, gain * CORPORATE_TAX_RATE + engine.holding_admin_cost)
        return (gain - tax) / amount, "Holding: 22 % selskabsskat + adminomkostning (ingen udlodning)."

    return r, "Ingen specifik skattemodel valgt; bruttoafkast anvendt."


def build_cash_counterfactual(
    years: int,
    initial_cash: float,
    yearly_free_cashflow: pd.Series,
    cash_rate: float,
    inflation_rate: float,
) -> pd.DataFrame:
    """Counterfactual where investable wealth is kept in cash and eroded by inflation."""
    cash_nominal = max(0.0, initial_cash)
    rows = []
    inflation_index = 1.0

    for year in range(1, years + 1):
        cf = float(yearly_free_cashflow.iloc[year - 1]) if year - 1 < len(yearly_free_cashflow) else 0.0
        cash_nominal = max(0.0, cash_nominal + cf)
        cash_nominal *= (1 + cash_rate)
        inflation_index *= (1 + inflation_rate)
        cash_real = cash_nominal / inflation_index
        rows.append(
            {
                "Year": year,
                "Cash Nominal": round(cash_nominal, 0),
                "Cash Real": round(cash_real, 0),
            }
        )

    return pd.DataFrame(rows)


def build_household_structuring_plan(
    engine: DanishTaxEngine,
    current_cash_holdings: float,
    reserve_target: float,
    ask_funded: float,
    annual_investment_capacity: float,
    weights: dict,
    world_return: float,
    years: int,
    ask_cap: float,
) -> tuple[pd.DataFrame, list, str]:
    """Create a concrete, consistent household plan from profile inputs."""
    ask_room = max(0.0, ask_cap - ask_funded)
    available_after_reserve = max(0.0, current_cash_holdings - reserve_target)
    ask_topup_now = min(ask_room, available_after_reserve)
    remaining_now = max(0.0, available_after_reserve - ask_topup_now)

    non_ask_weights = normalize_weights({k: v for k, v in weights.items() if k != "ask"})
    monthly_budget = max(0.0, annual_investment_capacity / 12)

    annual_gain_proxy = (remaining_now + max(0.0, annual_investment_capacity)) * max(0.0, world_return)
    holding_break_even = engine.holding_breakeven_analysis(
        portfolio_value=max(100_000.0, remaining_now),
        annual_return=max(0.01, world_return),
    )

    recommended_arch = "Private konti"
    if remaining_now >= holding_break_even["breakeven_portfolio"] and annual_gain_proxy > 120_000:
        recommended_arch = "Holding ApS"
    elif remaining_now >= 0.6 * holding_break_even["breakeven_portfolio"]:
        recommended_arch = "Hybrid"

    rows = [
        {
            "Handling": "Behold reserve",
            "Beløb nu (DKK)": round(min(current_cash_holdings, reserve_target), 0),
            "Månedligt bidrag (DKK)": 0,
            "Hvorfor": "Likvid sikkerhed før investering",
        },
        {
            "Handling": "Fyld ASK nu",
            "Beløb nu (DKK)": round(ask_topup_now, 0),
            "Månedligt bidrag (DKK)": round(min(monthly_budget, ask_room / 12), 0) if ask_room > 0 else 0,
            "Hvorfor": "17 % lagerbeskatning er mest skatteeffektiv",
        },
    ]

    label_map = {
        "private_etf": "World/ETF",
        "private_equity": "PE/Aktier",
        "holding": "Holding ApS",
        "bonds": "Defensiv",
    }
    for key in ["private_etf", "private_equity", "holding", "bonds"]:
        w = non_ask_weights.get(key, 0.0)
        if w <= 0:
            continue
        rows.append(
            {
                "Handling": f"Alloker til {label_map.get(key, key)}",
                "Beløb nu (DKK)": round(remaining_now * w, 0),
                "Månedligt bidrag (DKK)": round(monthly_budget * w, 0),
                "Hvorfor": "Rute efter valgt kontostruktur og målallokering",
            }
        )

    steps = [
        f"1. Hold mindst {fmt_dkk(reserve_target)} i likvid reserve.",
        f"2. Fyld ASK op med {fmt_dkk(ask_topup_now)} nu (ASK restplads: {fmt_dkk(max(0.0, ask_room - ask_topup_now))}).",
        f"3. Alloker resterende {fmt_dkk(remaining_now)} efter målmix og kontostruktur.",
        f"4. Invester løbende ca. {fmt_dkk(annual_investment_capacity)} årligt ({fmt_dkk(monthly_budget)} månedligt).",
        f"5. Revurdér LTV og kontoarkitektur årligt eller ved større indkomst-/renteændringer.",
    ]

    return pd.DataFrame(rows), steps, recommended_arch


def debt_optimization_analysis(
    annual_extra_capacity: float,
    years: int,
    expected_portfolio_return: float,
    mortgage_rate: float,
) -> dict:
    """Compare long-run effect of investing extra cash vs prepaying mortgage."""
    net_mortgage_rate = mortgage_rate * (1 - RENTEFRADRAG_TAX_VALUE)
    spread = expected_portfolio_return - net_mortgage_rate

    if expected_portfolio_return <= 0:
        invest_fv = annual_extra_capacity * years
    else:
        invest_fv = annual_extra_capacity * (((1 + expected_portfolio_return) ** years - 1) / expected_portfolio_return)

    if net_mortgage_rate <= 0:
        prepay_fv = annual_extra_capacity * years
    else:
        prepay_fv = annual_extra_capacity * (((1 + net_mortgage_rate) ** years - 1) / net_mortgage_rate)

    recommendation = "Invester meroverskud" if invest_fv >= prepay_fv else "Afdrag ekstra på gæld"
    return {
        "net_mortgage_rate": net_mortgage_rate,
        "spread": spread,
        "invest_fv": invest_fv,
        "prepay_fv": prepay_fv,
        "recommendation": recommendation,
        "value_delta": invest_fv - prepay_fv,
    }


def implementation_plan(annual_investment: float, weights: dict, ask_used: float, ask_cap: float) -> pd.DataFrame:
    """Create an execution-oriented monthly transfer plan by account bucket."""
    monthly = max(0.0, annual_investment / 12)
    weights = normalize_weights(weights)
    ask_room = max(0.0, ask_cap - ask_used)

    ask_monthly = min(monthly * weights.get("ask", 0.0), ask_room / 12)
    remaining = max(0.0, monthly - ask_monthly)

    non_ask = {k: v for k, v in weights.items() if k != "ask"}
    non_ask = normalize_weights(non_ask)

    rows = [
        {"Konto/Beholder": "ASK", "Månedlig overførsel": round(ask_monthly, 0), "Rationale": "Fyld ASK først (17 % lager)"}
    ]
    label_map = {
        "private_etf": "ETF (lager)",
        "private_equity": "Private aktier (realisering)",
        "holding": "Holding ApS",
        "bonds": "Obligationer/kontantnær",
    }
    for key, w in non_ask.items():
        rows.append(
            {
                "Konto/Beholder": label_map.get(key, key),
                "Månedlig overførsel": round(remaining * w, 0),
                "Rationale": "Fordeling efter målallokering",
            }
        )
    return pd.DataFrame(rows)


def simulate_mixed_portfolio(
    engine: DanishTaxEngine,
    years: int,
    starting_capital: float,
    annual_salary: float,
    effective_income_tax: float,
    annual_living_cost: float,
    annual_household_fixed: float,
    annual_car_depreciation: float,
    home_value: float,
    property_appreciation: float,
    property_tax_rate: float,
    property_maintenance_rate: float,
    annual_extra_cashflow: float,
    weights: dict,
    returns: dict,
    ask_already_funded: float,
    ask_start_balance: float,
    ask_cap: float,
    leverage_amount: float,
    mortgage_rate: float,
    retirement_start_year: int | None = None,
    phase_down_years: int = 0,
    salary_after_retirement_pct: float = 0.0,
    annual_public_pension: float = 0.0,
    annual_private_pension: float = 0.0,
    pension_tax_rate: float = 0.37,
    free_cashflow_invest_share: float = 1.0,
    annual_salary_growth: float = 0.0,
    inflation_rate: float = 0.0,
    emergency_reserve_target: float = 0.0,
    emergency_reserve_start: float = 0.0,
    glidepath_shift_to_bonds: float = 0.0,
    yearly_return_volatility: float = 0.0,
    regime_adjustments: dict = None,
    rng: np.random.Generator = None,
) -> pd.DataFrame:
    """Simulate household-to-investment cash flow and mixed-asset compounding."""
    balances = {
        "ask": 0.0,
        "private_etf": 0.0,
        "private_equity": 0.0,
        "holding": 0.0,
        "bonds": 0.0,
    }

    weights = normalize_weights(weights)
    ask_used = max(0.0, ask_already_funded)
    balances["ask"] += max(0.0, ask_start_balance)
    ask_used = max(ask_used, balances["ask"])
    regime_adjustments = regime_adjustments or {}
    vol_multiplier = regime_adjustments.get("vol_multiplier", 1.0)

    initial_pool = max(0.0, starting_capital) + max(0.0, leverage_amount)
    initial_alloc, ask_used = allocate_with_ask_cap(initial_pool, weights, ask_used, ask_cap=ask_cap)
    for k, v in initial_alloc.items():
        balances[k] += v

    cash_buffer = 0.0
    reserve_balance = max(0.0, emergency_reserve_start)
    property_value = max(0.0, home_value)
    records = []

    curr_salary = annual_salary
    curr_living = annual_living_cost
    curr_fixed = annual_household_fixed
    curr_car_dep = annual_car_depreciation
    curr_mortgage_rate = mortgage_rate + regime_adjustments.get("rate_shift", 0.0)
    curr_property_appreciation = property_appreciation + regime_adjustments.get("house_shift", 0.0)

    if rng is None:
        rng = np.random.default_rng(42)

    for year in range(1, years + 1):
        if year > 1:
            curr_salary *= (1 + annual_salary_growth)
            curr_living *= (1 + inflation_rate)
            curr_fixed *= (1 + inflation_rate)
            curr_car_dep *= (1 + inflation_rate)

        salary_factor = 1.0
        if retirement_start_year is not None:
            retirement_year = max(1, int(retirement_start_year))
            post_ret_factor = min(1.0, max(0.0, salary_after_retirement_pct / 100))
            phase_years = max(0, int(phase_down_years))
            phase_start = max(1, retirement_year - phase_years)

            if year >= retirement_year:
                salary_factor = post_ret_factor
            elif year >= phase_start and phase_years > 0:
                progress = (year - phase_start + 1) / max(1, (retirement_year - phase_start + 1))
                salary_factor = 1.0 + (post_ret_factor - 1.0) * progress

        gross_labor_income = curr_salary * salary_factor
        after_tax_salary = gross_labor_income * (1 - effective_income_tax)

        gross_pension_income = 0.0
        if retirement_start_year is not None and year >= max(1, int(retirement_start_year)):
            gross_pension_income = max(0.0, annual_public_pension) + max(0.0, annual_private_pension)
        after_tax_pension_income = gross_pension_income * (1 - min(0.70, max(0.0, pension_tax_rate)))
        property_value *= (1 + curr_property_appreciation)
        property_tax = property_value * property_tax_rate
        property_maintenance = property_value * property_maintenance_rate
        net_interest_cost = leverage_amount * curr_mortgage_rate * (1 - RENTEFRADRAG_TAX_VALUE)

        free_cash_flow = (
            after_tax_salary
            + after_tax_pension_income
            + annual_extra_cashflow
            - curr_living
            - curr_fixed
            - curr_car_dep
            - property_tax
            - property_maintenance
            - net_interest_cost
        )

        reserve_balance += free_cash_flow
        invest_share = min(1.0, max(0.0, free_cashflow_invest_share))
        if reserve_balance < 0:
            cash_buffer += reserve_balance
            reserve_balance = 0.0
            yearly_investment = 0.0
        elif reserve_balance <= emergency_reserve_target:
            yearly_investment = 0.0
        else:
            surplus_above_reserve = reserve_balance - emergency_reserve_target
            yearly_investment = surplus_above_reserve * invest_share
            reserve_balance = emergency_reserve_target + (surplus_above_reserve - yearly_investment)

        dyn_weights = glidepath_weights(weights, year, years, glidepath_shift_to_bonds)
        yearly_alloc, ask_used = allocate_with_ask_cap(yearly_investment, dyn_weights, ask_used, ask_cap=ask_cap)
        for k, v in yearly_alloc.items():
            balances[k] += v

        shock_scale = yearly_return_volatility * vol_multiplier
        r_ask = max(-0.95, returns["ask"] + regime_adjustments.get("return_shift", 0.0) + rng.normal(0, shock_scale))
        r_etf = max(-0.95, returns["private_etf"] + regime_adjustments.get("return_shift", 0.0) + rng.normal(0, shock_scale))
        r_eq = max(-0.95, returns["private_equity"] + regime_adjustments.get("return_shift", 0.0) + rng.normal(0, shock_scale))
        r_hold = max(-0.95, returns["holding"] + regime_adjustments.get("return_shift", 0.0) + rng.normal(0, shock_scale))
        r_bond = max(-0.95, returns["bonds"] + rng.normal(0, shock_scale * 0.5))

        ask_gain = balances["ask"] * r_ask
        ask_tax = ask_gain * ASK_TAX_RATE
        balances["ask"] += ask_gain - ask_tax

        etf_gain = balances["private_etf"] * r_etf
        etf_tax = engine.aktieindkomst_tax(etf_gain).tax_paid if etf_gain > 0 else 0.0
        balances["private_etf"] += etf_gain - etf_tax

        eq_gain = balances["private_equity"] * r_eq
        dividend_base = balances["private_equity"] * 0.02
        eq_dividend_tax = engine.aktieindkomst_tax(dividend_base).tax_paid if dividend_base > 0 else 0.0
        balances["private_equity"] += eq_gain - eq_dividend_tax

        holding_gain = balances["holding"] * r_hold
        holding_tax = max(0.0, holding_gain * CORPORATE_TAX_RATE + engine.holding_admin_cost)
        balances["holding"] += holding_gain - holding_tax

        bond_gain = balances["bonds"] * r_bond
        bond_tax = bond_gain * KAPITALINDKOMST_POS_RATE if bond_gain > 0 else 0.0
        balances["bonds"] += bond_gain - bond_tax

        total_portfolio = sum(balances.values())
        total_tax = ask_tax + etf_tax + eq_dividend_tax + holding_tax + bond_tax
        net_worth = total_portfolio + property_value + cash_buffer - leverage_amount

        records.append(
            {
                "Year": year,
                "Gross Labor Income": round(gross_labor_income, 0),
                "After-Tax Salary": round(after_tax_salary, 0),
                "After-Tax Pension": round(after_tax_pension_income, 0),
                "Free Cash Flow": round(free_cash_flow, 0),
                "Yearly Investment": round(yearly_investment, 0),
                "Portfolio Value": round(total_portfolio, 0),
                "Property Value": round(property_value, 0),
                "Cash Buffer": round(cash_buffer, 0),
                "Reserve Balance": round(reserve_balance, 0),
                "Tax Paid": round(total_tax, 0),
                "Net Worth": round(net_worth, 0),
                "ASK Balance": round(balances["ask"], 0),
                "ETF Balance": round(balances["private_etf"], 0),
                "Equity Balance": round(balances["private_equity"], 0),
                "Holding Balance": round(balances["holding"], 0),
                "Bond Balance": round(balances["bonds"], 0),
                "Dynamic Bond Weight": round(dyn_weights.get("bonds", 0.0), 4),
            }
        )

    return pd.DataFrame(records)


def run_monte_carlo(
    engine: DanishTaxEngine,
    simulations: int,
    regime_probs: dict,
    target_net_worth: float,
    **sim_kwargs,
) -> dict:
    """Run stochastic simulations with regime sampling and return risk statistics."""
    regimes = macro_regime_presets()
    names = list(regime_probs.keys())
    probs_raw = np.array([max(0.0, regime_probs[k]) for k in names], dtype=float)
    probs = probs_raw / probs_raw.sum() if probs_raw.sum() > 0 else np.ones(len(names)) / len(names)

    final_nw = []
    shortfall_years = []
    paths = []

    for i in range(max(1, simulations)):
        rng = np.random.default_rng(1000 + i)
        regime_name = rng.choice(names, p=probs)
        adjustments = regimes.get(regime_name, regimes["Base"])
        df = simulate_mixed_portfolio(
            engine=engine,
            regime_adjustments=adjustments,
            rng=rng,
            **sim_kwargs,
        )
        final_nw.append(float(df["Net Worth"].iloc[-1]))
        shortfall_years.append(int((df["Free Cash Flow"] < 0).sum()))
        paths.append(df["Net Worth"].values)

    arr = np.array(final_nw)
    path_arr = np.vstack(paths)
    p10 = np.percentile(path_arr, 10, axis=0)
    p50 = np.percentile(path_arr, 50, axis=0)
    p90 = np.percentile(path_arr, 90, axis=0)

    path_df = pd.DataFrame(
        {
            "Year": np.arange(1, path_arr.shape[1] + 1),
            "P10": p10,
            "P50": p50,
            "P90": p90,
        }
    )

    return {
        "prob_hit_target": float((arr >= target_net_worth).mean()),
        "p5": float(np.percentile(arr, 5)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "mean_shortfall_years": float(np.mean(shortfall_years)),
        "paths": path_df,
    }


# ══════════════════════════════════════════════════════════════════════
#  SIDEBAR  — Global Investor Profile
# ══════════════════════════════════════════════════════════════════════

def render_sidebar() -> DanishTaxEngine:
    """
    Render the global investor profile sidebar.
    Returns a configured DanishTaxEngine instance that the rest of
    the app uses for all calculations.
    """
    with st.sidebar:
        st.image(
            "https://upload.wikimedia.org/wikipedia/commons/9/9c/Flag_of_Denmark.svg",
            width=60
        )
        st.title("Min Investorprofil")
        st.caption("Disse indstillinger bruges i hele dashboardet.")

        st.divider()

        # ── Personal Status ───────────────────────────────────────────
        st.subheader("👤 Household Identitet")

        city = st.selectbox(
            "Byprofil",
            ["København", "Aarhus", "Anden kommune"],
            index=0,
            help="Global profil for kommuneskat og standardomkostninger.",
        )

        married = st.toggle(
            "Gift / samlevende (dobbelt aktieindkomsttærskel)",
            value=False,
            help=(
                "Gifte par kan kombinere den lave aktieindkomsttærskel: "
                f"{AKTIEINDKOMST_THRESHOLD_MARRIED:,.0f} DKK vs. "
                f"{AKTIEINDKOMST_THRESHOLD_SINGLE:,.0f} DKK for enlige."
            ),
        )

        annual_income = int_input_with_commas(
            "Brutto husholdningsindkomst (DKK/år)",
            key="sb_annual_income",
            min_value=0,
            max_value=20_000_000,
            value=700_000,
            step=25_000,
            help="Global baseindkomst for automatisk effektiv skat i simulatoren.",
        )

        st.divider()
        st.subheader("💵 Cash & ASK (Global)")

        current_cash_holdings = int_input_with_commas(
            "Likvid beholdning (DKK)",
            key="sb_current_cash",
            min_value=0,
            max_value=20_000_000,
            value=200_000,
            step=10_000,
            help="Samlet cash i husholdningen, bruges til reserve + counterfactual.",
        )
        reserve_months = st.slider(
            "Likvid reserve (måneder)",
            min_value=3,
            max_value=24,
            value=9,
            step=1,
            help="Global reservepolitik for hele modellen.",
        )

        ask_cap = household_ask_cap(married)
        ask_is_filled = st.toggle("ASK er allerede fyldt", value=False)
        if ask_is_filled:
            ask_funded = float(ask_cap)
            st.caption(f"ASK låst til household-cap: {ask_cap:,.0f} DKK")
        else:
            ask_funded = float(
                int_input_with_commas(
                    "Aktuelt ASK indskud (DKK)",
                    key="sb_ask_funded",
                    min_value=0,
                    max_value=int(ask_cap),
                    value=0,
                    step=5_000,
                )
            )

        account_arch_pref = st.selectbox(
            "Kontoarkitektur udenfor ASK",
            ["Private konti", "Holding ApS", "Hybrid"],
            index=0,
            help="Global standard for kontoopsætning i scenarier.",
        )

        st.divider()

        # ── Holding Company ───────────────────────────────────────────
        st.subheader("🏢 Holding ApS Overhead")

        holding_admin = st.slider(
            "Holding ApS admin. omkostninger (DKK/år)",
            min_value=5_000,
            max_value=50_000,
            value=int(HOLDING_DEFAULT_ADMIN_COST),
            step=1_000,
            help=(
                "Revisor, LEI-kode, Erhvervsstyrelsen årsrapport, m.m. "
                f"Standard: {HOLDING_DEFAULT_ADMIN_COST:,.0f} DKK/år."
            ),
        )

        st.divider()

        # ── Info box with live tax rates ──────────────────────────────
        st.subheader("📋 2026 Skattesatser")
        st.markdown(
            f"""
| Skat | Sats |
|------|------|
| Aktieindkomst (lav) | **{AKTIEINDKOMST_LOW_RATE*100:.0f} %** |
| Aktieindkomst (høj) | **{AKTIEINDKOMST_HIGH_RATE*100:.0f} %** |
| ASK (lager) | **{ASK_TAX_RATE*100:.0f} %** |
| Selskabsskat (ApS) | **{CORPORATE_TAX_RATE*100:.0f} %** |
| Rentefradrag (nettoværdi) | **~{RENTEFRADRAG_TAX_VALUE*100:.0f} %** |
| ASK indskudsgrænse (pr. person) | **{ASK_DEPOSIT_LIMIT:,.0f} DKK** |
| ASK household-cap (profil) | **{ask_cap:,.0f} DKK** |
            """
        )

        st.caption(
            "ℹ️ Skattesatser er hardkodet i `tax_engine.py`. "
            "Opdater konstanterne dér ved fremtidige regelændringer."
        )

    st.session_state["household_profile"] = {
        "city": city,
        "married": married,
        "annual_income": float(annual_income),
        "current_cash_holdings": float(current_cash_holdings),
        "reserve_months": int(reserve_months),
        "ask_is_filled": bool(ask_is_filled),
        "ask_funded": float(ask_funded),
        "ask_cap": float(ask_cap),
        "account_arch_pref": account_arch_pref,
        "holding_admin": float(holding_admin),
    }

    # Return configured engine for use in all modules
    return DanishTaxEngine(
        married=married,
        annual_income=annual_income,
        holding_admin_cost=holding_admin,
    )


# ══════════════════════════════════════════════════════════════════════
#  MODULE 1 — TAX VEHICLE EXPLAINER (Overview Tab)
# ══════════════════════════════════════════════════════════════════════

def render_overview(engine: DanishTaxEngine):
    """
    Profile-driven overview that explains how the app converts household inputs
    into concrete investment structure decisions.
    """
    st.header("🏠 Overblik — Fra Household Profil til Investeringsstruktur")
    st.markdown(
        """
        Overblik-siden viser **hvordan appen tænker**. Den bruger din globale profil i venstre panel
        til at beslutte: 1) reserve, 2) ASK-topup, 3) kontostruktur udenfor ASK, 4) gearing-kandidater.
        """
    )

    profile = st.session_state.get("household_profile", {})
    city = profile.get("city", "København")
    cprof = city_profile(city)
    annual_income = float(profile.get("annual_income", engine.annual_income))
    current_cash = float(profile.get("current_cash_holdings", 200_000.0))
    reserve_months = int(profile.get("reserve_months", 9))
    ask_funded = float(profile.get("ask_funded", 0.0))
    ask_cap = float(profile.get("ask_cap", household_ask_cap(engine.married)))
    account_arch = profile.get("account_arch_pref", "Private konti")

    auto_eff_tax = estimate_effective_income_tax(annual_income, cprof["municipal_tax"], engine.married)
    annual_living_proxy = cprof["monthly_living"] * 12
    reserve_target = (annual_living_proxy / 12) * reserve_months
    ask_room = max(0.0, ask_cap - ask_funded)
    investable_now = max(0.0, current_cash - reserve_target)
    ask_top_up_now = min(ask_room, investable_now)
    outside_ask_now = max(0.0, investable_now - ask_top_up_now)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Effektiv skat (auto)", fmt_pct(auto_eff_tax), city)
    m2.metric("Reserve-mål", fmt_dkk(reserve_target), f"{reserve_months} mdr")
    m3.metric("ASK restplads", fmt_dkk(ask_room))
    m4.metric("Investerbar nu-likviditet", fmt_dkk(investable_now))

    st.subheader("🚦 Hurtig status")

    def render_status_card(title: str, signal: str, value: str, detail: str, color: str):
        st.markdown(
            f"""
            <div style="border:1px solid #D9E1E7; border-left:7px solid {color}; border-radius:10px; padding:12px 14px; background:#F8FAFC; min-height:140px;">
                <div style="font-size:0.86rem; color:#546E7A; margin-bottom:4px;">{title}</div>
                <div style="font-size:1.05rem; font-weight:700; color:#102A43; margin-bottom:2px;">{signal}</div>
                <div style="font-size:1.2rem; font-weight:700; color:#0B1F33; margin-bottom:6px;">{value}</div>
                <div style="font-size:0.82rem; color:#486581;">{detail}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    reserve_coverage = (current_cash / reserve_target) if reserve_target > 0 else 1.0
    if reserve_coverage >= 1.0:
        reserve_signal = "Grøn - reserve på plads"
        reserve_color = "#1B8A5A"
    elif reserve_coverage >= 0.7:
        reserve_signal = "Gul - næsten i mål"
        reserve_color = "#D48A00"
    else:
        reserve_signal = "Rød - reserve under mål"
        reserve_color = "#B42318"

    ask_utilization = min(1.0, ask_funded / ask_cap) if ask_cap > 0 else 1.0
    if ask_utilization >= 0.9:
        ask_signal = "Grøn - ASK næsten fyldt"
        ask_color = "#1B8A5A"
    elif ask_utilization >= 0.5:
        ask_signal = "Gul - ASK delvist udnyttet"
        ask_color = "#D48A00"
    else:
        ask_signal = "Rød - ASK lav udnyttelse"
        ask_color = "#B42318"

    proxy_amount = max(100_000.0, outside_ask_now)
    etf_post_tax, _ = expected_post_tax_return_for_vehicle(
        engine=engine,
        gross_return=0.07,
        vehicle="private_etf",
        invested_amount=proxy_amount,
        ask_room=ask_room,
    )
    debt_rate = float(cprof.get("heloc_rate", 0.04))
    net_debt_rate = debt_rate * (1 - RENTEFRADRAG_TAX_VALUE)
    post_tax_spread = etf_post_tax - net_debt_rate
    if post_tax_spread >= 0.02:
        gear_signal = "Grøn - spread robust"
        gear_color = "#1B8A5A"
    elif post_tax_spread >= 0.0:
        gear_signal = "Gul - spread tynd"
        gear_color = "#D48A00"
    else:
        gear_signal = "Rød - negativ spread"
        gear_color = "#B42318"

    s1, s2, s3 = st.columns(3)
    with s1:
        render_status_card(
            "Reserve-parathed",
            reserve_signal,
            f"Dækning: {reserve_coverage*100:.0f}%",
            f"Likvid beholdning {fmt_dkk(current_cash)} vs mål {fmt_dkk(reserve_target)}.",
            reserve_color,
        )
    with s2:
        render_status_card(
            "ASK-udnyttelse",
            ask_signal,
            f"{ask_utilization*100:.0f}% udnyttet",
            f"ASK finansieret {fmt_dkk(ask_funded)} af cap {fmt_dkk(ask_cap)}.",
            ask_color,
        )
    with s3:
        render_status_card(
            "Gearing-parathed",
            gear_signal,
            f"Post-tax spread: {post_tax_spread*100:.2f}%-point",
            f"ETF post-tax {etf_post_tax*100:.2f}% minus nettorente {net_debt_rate*100:.2f}%.",
            gear_color,
        )

    st.subheader("🔄 Kapitalrouting (fra profil-cash)")
    sankey = go.Figure(
        go.Sankey(
            node=dict(
                label=[
                    "Likvid beholdning",
                    "Likvid reserve",
                    "ASK top-up",
                    "Udenfor ASK",
                ],
                pad=18,
                thickness=18,
                color=["#455A64", "#26A69A", "#2E7D32", "#1565C0"],
            ),
            link=dict(
                source=[0, 0, 0],
                target=[1, 2, 3],
                value=[
                    min(current_cash, reserve_target),
                    ask_top_up_now,
                    outside_ask_now,
                ],
                color=["rgba(38,166,154,0.35)", "rgba(46,125,50,0.35)", "rgba(21,101,192,0.35)"],
            ),
        )
    )
    sankey.update_layout(height=320, paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(sankey, use_container_width=True)

    route_df = pd.DataFrame(
        {
            "Trin": [
                "1) Likvid reserve",
                "2) ASK top-up",
                "3) Investerbar udenfor ASK",
            ],
            "Beløb nu": [
                fmt_dkk(min(current_cash, reserve_target)),
                fmt_dkk(ask_top_up_now),
                fmt_dkk(outside_ask_now),
            ],
            "Hvad betyder det": [
                "Buffer til uforudsete udgifter og stabilt cashflow.",
                "Fylder skatteeffektiv ASK-kapacitet først.",
                "Allokeres i valgt kontoarkitektur (privat/holding/hybrid).",
            ],
        }
    )
    st.dataframe(route_df, width="stretch", hide_index=True)
    st.caption(
        "Læs grafen fra venstre mod højre: den viser kun din nuværende likviditet fordelt i prioriteret rækkefølge, "
        "ikke en afkastprognose i sig selv. Prognoser vises i Scenario Simulatoren."
    )

    st.subheader("🧭 Kontostruktur: hvad betyder dit valg?")
    arch_df = pd.DataFrame(
        [
            {"Arkitektur": "Private konti", "Bruges når": "Ønsker enkelhed og direkte ejerskab", "Skattemotor": "Aktie/ETF privat"},
            {"Arkitektur": "Holding ApS", "Bruges når": "Stor kapital + langsigtet reinvestering", "Skattemotor": "22 % selskabsskat + overhead"},
            {"Arkitektur": "Hybrid", "Bruges når": "Ønsker fleksibilitet mellem privat og selskab", "Skattemotor": "Kombineret"},
        ]
    )
    st.dataframe(arch_df, width="stretch", hide_index=True)
    st.info(f"Aktuel global præference i venstre panel: **{account_arch}**")

    with st.expander("🏢 Holding ApS: praktiske fordele og trade-offs", expanded=False):
        st.markdown(
            """
**Fordele ved videreføring af midler (familie/generation):**
- Midler kan blive i selskabet og reinvesteres uden privat udlodning hvert år.
- Ejerskab kan struktureres via anparter, som kan overdrages gradvist (kræver juridisk/skatterådgivning).
- Giver bedre ramme for fælles familieformål, når kapital skal forvaltes over længere tid.

**Fordele ved investering i unoterede aktieposter:**
- Holding er ofte et mere naturligt investeringskøretøj til illikvide/unoterede cases.
- Gevinster kan i mange cases geninvesteres i selskabet før privat udlodning.
- Bedre operationel adskillelse mellem privat økonomi og høj-risiko/illikvide investeringer.

**Vigtige trade-offs:**
- Årlige administrationsomkostninger, compliance og regnskab.
- Dobbelt lag af skat kan opstå ved senere privat udlodning.
- Kræver disciplineret governance (ejeraftale, fuldmagter, succession-plan).
            """
        )
        st.caption(
            "Dette er en forenklet beslutningsstøtte. Konkrete succession-/overdragelsesforhold skal vurderes af revisor/advokat."
        )

        st.markdown("**Hvorfor kan Holding give mening ved familieoverdragelse (lang sigt)?**")
        st.markdown(
            """
- **Skatteudskydelse i praksis:** afkast kan blive i selskabet og geninvesteres efter selskabsskat, uden at udløse privat udbytteskat hvert år.
- **Kontrolleret generationsskifte:** anparter kan overdrages gradvist, så værditilvækst i højere grad kan flytte over i næste generation over tid.
- **Bedre planlægningsrum:** familie kan arbejde med ejeraftale, stemmerettigheder og timing af udlodninger i stedet for at realisere privat løbende.

Langsigtet pointe: jo længere kapitalen kan arbejde inde i strukturen før privat udlodning, jo større bliver effekten af udskudt privatbeskatning.
            """
        )

        st.markdown("**Hvordan foregår overdragelse af anparter typisk? (forenklet)**")
        transfer_steps = pd.DataFrame(
            {
                "Trin": [
                    "1) Struktur",
                    "2) Værdiansættelse",
                    "3) Overdragelse i etaper",
                    "4) Governance",
                    "5) Udlodningspolitik",
                ],
                "Hvad der sker": [
                    "Familieformue samles i holdingselskab i stedet for spredte private depoter.",
                    "Anparter prissættes (typisk med rådgiver), så overdragelse sker på dokumenteret grundlag.",
                    "Anparter gives/sælges gradvist over flere år i stedet for alt på én gang.",
                    "Ejeraftale fastlægger stemmer, vetoret, roller og konfliktløsning.",
                    "Familien styrer hvornår der udloddes privat, og hvornår kapitalen bliver i selskabet.",
                ],
                "Hvorfor det kan give mening": [
                    "Mere samlet kapitalforvaltning og bedre kontinuitet.",
                    "Reducerer risiko for skattemæssige tvister senere.",
                    "Gør generationsskifte operationelt mere robust.",
                    "Forebygger fremtidige familie-/ejerskabskonflikter.",
                    "Maksimerer compounding før privat beskatning.",
                ],
            }
        )
        st.dataframe(transfer_steps, width="stretch", hide_index=True)

        st.markdown("**Illustrativt rationale (ikke rådgivning): hvorfor timing af privat skat betyder noget**")
        example_base = 1_000_000
        example_return = 0.08
        years_example = 10
        corp_after_tax = example_return * (1 - CORPORATE_TAX_RATE)
        gross_company_value = example_base * ((1 + corp_after_tax) ** years_example)
        distributed_company_value = gross_company_value * (1 - AKTIEINDKOMST_HIGH_RATE)

        private_after_tax_return = example_return * (1 - AKTIEINDKOMST_HIGH_RATE)
        private_value = example_base * ((1 + private_after_tax_return) ** years_example)

        illustration_df = pd.DataFrame(
            {
                "Spor": [
                    "Selskabsspor: først reinvestering i Holding (22 %), udlodning til sidst",
                    "Privat spor: afkast beskattes løbende med høj aktieindkomstsats",
                ],
                f"Værdi efter {years_example} år": [
                    fmt_dkk(distributed_company_value),
                    fmt_dkk(private_value),
                ],
                "Forklaring": [
                    "Privat skat udskydes til udlodningstidspunkt; kapital arbejder længere i selskabet.",
                    "Løbende privatbeskatning reducerer den kapital, der kan geninvesteres hvert år.",
                ],
            }
        )
        st.dataframe(illustration_df, width="stretch", hide_index=True)
        st.caption(
            "Eksemplet er forenklet og afhænger af konkrete regler om udbytte, succession, gave/arv og værdiansættelse. "
            "Brug altid revisor/advokat før implementering."
        )

        st.markdown("**Interaktiv mini-kalkulator: udskudt privat skat vs løbende privat skat**")
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            calc_start = int_input_with_commas(
                "Startkapital (DKK)",
                key="holding_calc_start_capital",
                min_value=100_000,
                max_value=100_000_000,
                value=2_000_000,
                step=100_000,
            )
        with k2:
            calc_years = st.slider("Horisont (år)", 5, 40, 15, key="holding_calc_years")
        with k3:
            calc_return = st.slider("Bruttoafkast (% p.a.)", 2.0, 15.0, 8.0, 0.25, key="holding_calc_return") / 100
        with k4:
            calc_private_tax = st.slider(
                "Privat effektiv afkastskat (%)",
                10.0,
                55.0,
                AKTIEINDKOMST_HIGH_RATE * 100,
                0.5,
                key="holding_calc_private_tax",
            ) / 100

        calc_corp_after_tax = calc_return * (1 - CORPORATE_TAX_RATE)
        calc_holding_pre_distribution = calc_start * ((1 + calc_corp_after_tax) ** calc_years)
        calc_holding_final = calc_holding_pre_distribution * (1 - calc_private_tax)

        calc_private_after_tax_return = calc_return * (1 - calc_private_tax)
        calc_private_final = calc_start * ((1 + calc_private_after_tax_return) ** calc_years)
        calc_delta = calc_holding_final - calc_private_final

        r1, r2, r3 = st.columns(3)
        r1.metric("Holding-spor (udlodning ved slut)", fmt_dkk(calc_holding_final))
        r2.metric("Privat spor (løbende skat)", fmt_dkk(calc_private_final))
        r3.metric("Forskel", fmt_dkk(calc_delta))

        years_axis = np.arange(0, calc_years + 1)
        private_path = calc_start * np.power(1 + calc_private_after_tax_return, years_axis)
        holding_pre_path = calc_start * np.power(1 + calc_corp_after_tax, years_axis)

        calc_fig = go.Figure()
        calc_fig.add_trace(
            go.Scatter(
                x=years_axis,
                y=private_path,
                mode="lines",
                name="Privat (løbende skat)",
                line=dict(color="#1565C0", width=3),
            )
        )
        calc_fig.add_trace(
            go.Scatter(
                x=years_axis,
                y=holding_pre_path,
                mode="lines",
                name="Holding (før udlodning)",
                line=dict(color="#2E7D32", width=3),
            )
        )
        calc_fig.add_trace(
            go.Scatter(
                x=[calc_years],
                y=[calc_holding_final],
                mode="markers",
                name="Holding (efter udlodning i slutår)",
                marker=dict(color="#2E7D32", size=11, symbol="diamond"),
            )
        )
        calc_fig.update_layout(
            title="År-for-år divergens: privat løbende skat vs holding med udlodning i slutår",
            xaxis_title="År",
            yaxis_title="DKK",
            height=320,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            hovermode="x unified",
        )
        st.plotly_chart(calc_fig, use_container_width=True)
        st.caption(
            "Grøn linje er kapital i selskabet før privat udlodning. Grøn diamant viser værdi efter privat skat ved udlodning i slutåret."
        )

        calc_df = pd.DataFrame(
            {
                "Trin": [
                    "Bruttoafkast",
                    "Afkast efter selskabsskat",
                    "Holding værdi før udlodning (slutår)",
                    "Holding værdi efter privat skat ved udlodning",
                    "Privat afkast efter løbende skat",
                    "Privat værdi (slutår)",
                ],
                "Værdi": [
                    fmt_pct(calc_return),
                    fmt_pct(calc_corp_after_tax),
                    fmt_dkk(calc_holding_pre_distribution),
                    fmt_dkk(calc_holding_final),
                    fmt_pct(calc_private_after_tax_return),
                    fmt_dkk(calc_private_final),
                ],
            }
        )
        st.dataframe(calc_df, width="stretch", hide_index=True)

        st.markdown("**Hvornår giver Holding typisk mening? (indikator)**")
        t1, t2 = st.columns(2)
        with t1:
            cap_medium_threshold = int_input_with_commas(
                "Tærskel: moderat kapital udenfor ASK (DKK)",
                key="overview_holding_cap_medium",
                min_value=100_000,
                max_value=5_000_000,
                value=400_000,
                step=50_000,
            )
            cap_high_threshold = int_input_with_commas(
                "Tærskel: høj kapital udenfor ASK (DKK)",
                key="overview_holding_cap_high",
                min_value=200_000,
                max_value=10_000_000,
                value=1_000_000,
                step=50_000,
            )
        with t2:
            income_medium_threshold = int_input_with_commas(
                "Tærskel: mellem-høj indkomst (DKK/år)",
                key="overview_holding_income_medium",
                min_value=300_000,
                max_value=3_000_000,
                value=800_000,
                step=25_000,
            )
            income_high_threshold = int_input_with_commas(
                "Tærskel: høj indkomst (DKK/år)",
                key="overview_holding_income_high",
                min_value=400_000,
                max_value=5_000_000,
                value=1_200_000,
                step=25_000,
            )

        cap_high_threshold = max(cap_high_threshold, cap_medium_threshold + 50_000)
        income_high_threshold = max(income_high_threshold, income_medium_threshold + 25_000)

        unlisted_focus = st.toggle(
            "Plan om investering i unoterede aktieposter via selskab",
            value=False,
            key="overview_holding_unlisted_focus",
        )
        family_succession_focus = st.toggle(
            "Ønske om gradvis familieoverdragelse/succession",
            value=False,
            key="overview_holding_family_focus",
        )

        fit_score = 0
        factors = []

        if outside_ask_now >= cap_high_threshold:
            fit_score += 35
            factors.append("Stor investerbar kapital udenfor ASK (+35)")
        elif outside_ask_now >= cap_medium_threshold:
            fit_score += 20
            factors.append("Moderat investerbar kapital udenfor ASK (+20)")
        else:
            fit_score += 5
            factors.append("Begrænset investerbar kapital udenfor ASK (+5)")

        if annual_income >= income_high_threshold:
            fit_score += 25
            factors.append("Høj husholdningsindkomst (+25)")
        elif annual_income >= income_medium_threshold:
            fit_score += 15
            factors.append("Mellem-høj husholdningsindkomst (+15)")
        else:
            fit_score += 5
            factors.append("Lavere husholdningsindkomst (+5)")

        if ask_room <= 0:
            fit_score += 10
            factors.append("ASK er fyldt, fokus flytter udenfor ASK (+10)")

        if account_arch in ("Holding ApS", "Hybrid"):
            fit_score += 10
            factors.append("Valgt arkitektur indeholder allerede selskabselement (+10)")

        if unlisted_focus:
            fit_score += 15
            factors.append("Unoteret investeringsfokus (+15)")
        if family_succession_focus:
            fit_score += 15
            factors.append("Familie-/succession-fokus (+15)")

        if fit_score >= 70:
            fit_label = "Høj relevans"
            fit_hint = "Holding kan være strukturelt relevant at analysere i dybden."
        elif fit_score >= 40:
            fit_label = "Mellem relevans"
            fit_hint = "Holding kan være relevant i hybrid opsætning, afhængigt af tidshorisont og governance."
        else:
            fit_label = "Lav relevans"
            fit_hint = "Privat struktur er ofte enklere på nuværende niveau; Holding kan revurderes senere."

        f1, f2 = st.columns([1, 2])
        f1.metric("Holding-fit score", f"{fit_score}/100", fit_label)
        f2.info(fit_hint)

        factor_df = pd.DataFrame({"Bidrag": factors})
        st.dataframe(factor_df, width="stretch", hide_index=True)

    st.subheader("📌 Hvad appen gør for dig")
    c1, c2, c3 = st.columns(3)
    c1.markdown(
        """
**1) Diagnose**
- Beregner automatisk effektiv skat
- Forklarer cashflow linje-for-linje
- Viser real købekraft for cash
        """
    )
    c2.markdown(
        """
**2) Strukturering**
- Fylder ASK cap-first
- Respekterer kontoarkitektur
- Udleder konkrete nu-beløb og månedlige bidrag
        """
    )
    c3.markdown(
        """
**3) Risiko & Robusthed**
- Makroregimer (Base/Bull/Bear)
- Monte Carlo sandsynligheder
- Gearing guidance med post-tax spread
        """
    )

    st.subheader("⚡ Standardantagelser for simulatorens prefill")
    ret_df = pd.DataFrame(
        {
            "Serie": ["World/S&P", "PE premium", "Obligationer", "Bolig"],
            "Default": ["7.0 %", "+2.0 %-point", "3.0 %", "4.0 %"],
            "Bemærkning": [
                "Bruges som equity baseline",
                "Justeres oven på world",
                "Defensiv bucket",
                "Før ejendomsskat/vedligehold",
            ],
        }
    )
    st.dataframe(ret_df, width="stretch", hide_index=True)


# ══════════════════════════════════════════════════════════════════════
#  MODULE 2 — SCENARIO SIMULATOR
# ══════════════════════════════════════════════════════════════════════

def render_scenario_simulator(engine: DanishTaxEngine):
    """
    Household-aware mixed portfolio simulator with advanced planning modules.
    """
    st.header("🎓 Scenario Simulator — Strategisk Porteføljeplan")
    st.markdown(
        """
        Simuler hele økonomien fra **bruttoindkomst → skat → leveomkostninger → fri investeringscashflow**.
        Modellen kombinerer ASK, ETF, aktier, Holding, obligationer, bolig, reservepolitik og gældsvalg.
        """
    )

    with st.expander("Sådan bruges modellen som husholdning (5 trin)", expanded=True):
        st.markdown(
            """
1. Udfyld husholdningsprofilen med indkomst, bolig, udgifter og likvid beholdning.
2. Vælg global kontostruktur udenfor ASK i venstre panel og sæt afkastantagelser.
3. Kontrollér gearing guidance: post-tax afkast skal være højere end nettorenten efter fradrag.
4. Brug Monte Carlo til at se sandsynlighed for målopnåelse og downside-risiko.
5. Følg den konkrete husholdnings-anbefaling nederst for "nu-beløb" og månedlige bidrag.
            """
        )

    regimes = macro_regime_presets()
    st.subheader("0) Makro-regime")
    rg1, rg2 = st.columns([2, 3])
    with rg1:
        selected_regime = st.selectbox("Vælg regime", list(regimes.keys()), index=0)
        regime = regimes[selected_regime]
    with rg2:
        st.caption(
            f"Regime antagelser: lønvækst {regime['salary_growth']*100:.1f}% | inflation {regime['inflation']*100:.1f}% | "
            f"afkastskift {regime['return_shift']*100:.1f}%-point | renteskift {regime['rate_shift']*100:.1f}%-point"
        )

    profile = st.session_state.get("household_profile", {})
    city = profile.get("city", "København")
    cprof = city_profile(city)
    annual_salary = float(profile.get("annual_income", engine.annual_income))
    ask_funded = float(profile.get("ask_funded", 0.0))
    ask_cap = float(profile.get("ask_cap", household_ask_cap(engine.married)))
    ask_start_balance = ask_funded
    current_cash_holdings = float(profile.get("current_cash_holdings", 200_000.0))
    reserve_months = int(profile.get("reserve_months", 9))
    account_arch = profile.get("account_arch_pref", "Private konti")

    st.subheader("1) Investorprofil og husholdning (fra venstre panel)")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Byprofil", city)
    p2.metric("Bruttoindkomst", fmt_dkk(annual_salary))
    p3.metric("Likvid beholdning", fmt_dkk(current_cash_holdings))
    p4.metric("ASK finansieret", fmt_dkk(ask_funded))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        years = st.slider("Investeringshorisont (år)", 5, 40, 20)
    with col2:
        auto_eff_tax = estimate_effective_income_tax(annual_salary, cprof["municipal_tax"], engine.married)
        tax_adjustment_pp = st.slider("Skattejustering (procentpoint)", -8.0, 8.0, 0.0, 0.5,
                                      help="Finjustering til individuelle fradrag/forhold oven på automatisk bracket-beregning.")
        effective_income_tax = min(0.70, max(0.0, auto_eff_tax + tax_adjustment_pp / 100))
        st.metric("Automatisk effektiv skat", fmt_pct(effective_income_tax),
                  f"Bracket-model + justering {tax_adjustment_pp:+.1f} pp")
        annual_extra_cashflow = int_input_with_commas(
            "Anden årlig netto cashflow (+/- DKK)",
            key="sim_annual_extra_cashflow",
            min_value=-2_000_000,
            max_value=2_000_000,
            value=0,
            step=10_000,
        )
    with col3:
        annual_living_cost = int_input_with_commas(
            "Leveomkostninger (DKK/år)",
            key="sim_annual_living_cost",
            min_value=0,
            max_value=5_000_000,
            value=int(cprof["monthly_living"] * 12),
            step=10_000,
        )
        annual_household_fixed = int_input_with_commas(
            "Store faste udgifter (DKK/år)",
            key="sim_annual_household_fixed",
            min_value=0,
            max_value=2_000_000,
            value=120_000,
            step=5_000,
            help="Fx institution, forsikringer, rejser, renovation m.m.",
        )
        annual_car_depreciation = int_input_with_commas(
            "Bilafskrivning / værditab (DKK/år)",
            key="sim_annual_car_dep",
            min_value=0,
            max_value=1_000_000,
            value=int(cprof["car_depreciation"]),
            step=5_000,
        )
    with col4:
        home_value = int_input_with_commas(
            "Boligværdi (DKK)",
            key="sim_home_value",
            min_value=0,
            max_value=50_000_000,
            value=4_500_000,
            step=100_000,
        )
        property_appreciation = st.slider("Boligafkast før drift (%)", -5.0, 10.0, 4.0, 0.25) / 100
        property_tax_rate = st.slider("Ejendomsskat (% af værdi)", 0.0, 2.5, round(cprof["property_tax_rate"] * 100, 2), 0.05) / 100
        property_maintenance_rate = st.slider("Boligvedligehold/drift (% af værdi)", 0.0, 2.5, round(cprof["property_maintenance_rate"] * 100, 2), 0.05) / 100

    st.subheader("1a) Arbejdsliv og pension")
    rp1, rp2, rp3, rp4 = st.columns(4)
    with rp1:
        enable_retirement = st.toggle("Planlæg nedtrapning/pension", value=False)
        retirement_in_years = st.slider("Pension om (år)", 0, years, min(10, years)) if enable_retirement else years + 1
    with rp2:
        phase_down_years = st.slider("Nedtrapning før pension (år)", 0, 15, 3) if enable_retirement else 0
        salary_after_retirement_pct = (
            st.slider("Arbejdsløn efter pension (% af nu)", 0, 100, 0, 5) if enable_retirement else 100
        )
    with rp3:
        annual_public_pension = int_input_with_commas(
            "Offentlig pension (DKK/år)",
            key="sim_public_pension",
            min_value=0,
            max_value=2_000_000,
            value=180_000,
            step=5_000,
        )
    with rp4:
        annual_private_pension = int_input_with_commas(
            "Privat pension (DKK/år)",
            key="sim_private_pension",
            min_value=0,
            max_value=3_000_000,
            value=120_000,
            step=5_000,
        )
        pension_tax_rate = st.slider("Skat på pensionsindkomst (%)", 15.0, 60.0, 37.0, 0.5) / 100

    retirement_start_year = (retirement_in_years + 1) if enable_retirement else None

    st.subheader("1b) Cash & reservepolitik")
    rv1, rv2 = st.columns(2)
    with rv1:
        cash_yield = st.slider("Kontant rente (% p.a.)", 0.0, 8.0, 1.5, 0.1) / 100
        invest_share_pct = st.slider(
            "Andel af fri cashflow til investering (%)",
            min_value=0,
            max_value=100,
            value=80,
            step=5,
            help="Resten beholdes som ekstra likviditet/buffer over reserve.",
        )
    with rv2:
        monthly_base_spend = (annual_living_cost + annual_household_fixed + annual_car_depreciation) / 12
        reserve_target = monthly_base_spend * reserve_months
        starting_capital = max(0.0, current_cash_holdings - reserve_target)
        st.metric("Reserve-mål (fra profil)", fmt_dkk(reserve_target), f"{reserve_months} måneder")
        st.metric("Investerbar kapital udenfor ASK (auto)", fmt_dkk(starting_capital), "Likvid beholdning - reserve")
        st.caption("Reserve trækkes automatisk fra profilens cash-balance.")

    st.subheader("2) Gearing (friværdi til investering)")
    col_lev1, col_lev2, col_lev3 = st.columns(3)
    with col_lev1:
        ltv = st.slider("Belåningsgrad på bolig (LTV %)", 0, 80, 0, 5)
    with col_lev2:
        mortgage_rate = st.slider("Realkreditrente (% p.a.)", 1.0, 8.0, 4.0, 0.25) / 100
    with col_lev3:
        leverage_amount = home_value * ltv / 100
        net_rate = (mortgage_rate + regime.get("rate_shift", 0.0)) * (1 - RENTEFRADRAG_TAX_VALUE)
        st.metric("Lånebeløb", fmt_dkk(leverage_amount))
        st.metric("Nettorente efter fradrag", fmt_pct(net_rate))

    st.subheader("2a) Cash flow statement (fra investorprofil)")
    if retirement_start_year is not None and retirement_start_year <= 1:
        year1_salary_factor = salary_after_retirement_pct / 100
    elif retirement_start_year is not None and phase_down_years > 0:
        phase_start = max(1, retirement_start_year - phase_down_years)
        if 1 >= phase_start and 1 < retirement_start_year:
            progress = (1 - phase_start + 1) / max(1, (retirement_start_year - phase_start + 1))
            year1_salary_factor = 1.0 + ((salary_after_retirement_pct / 100) - 1.0) * progress
        else:
            year1_salary_factor = 1.0
    else:
        year1_salary_factor = 1.0

    year1_gross_salary = annual_salary * year1_salary_factor
    year1_after_tax_income = year1_gross_salary * (1 - effective_income_tax)
    year1_gross_pension = (
        (annual_public_pension + annual_private_pension)
        if retirement_start_year is not None and retirement_start_year <= 1
        else 0.0
    )
    year1_after_tax_pension = year1_gross_pension * (1 - pension_tax_rate)
    year1_property_tax = home_value * (1 + property_appreciation) * property_tax_rate
    year1_property_maint = home_value * (1 + property_appreciation) * property_maintenance_rate
    year1_net_interest = leverage_amount * (mortgage_rate + regime.get("rate_shift", 0.0)) * (1 - RENTEFRADRAG_TAX_VALUE)
    year1_free_cf = (
        year1_after_tax_income
        + year1_after_tax_pension
        + annual_extra_cashflow
        - annual_living_cost
        - annual_household_fixed
        - annual_car_depreciation
        - year1_property_tax
        - year1_property_maint
        - year1_net_interest
    )
    year1_direct_invest = max(0.0, year1_free_cf * (invest_share_pct / 100))

    cf_statement = pd.DataFrame(
        {
            "Led": [
                "Efter-skat løn",
                "Efter-skat pension",
                "Anden netto cashflow",
                "Leveomkostninger",
                "Store faste udgifter",
                "Bilafskrivning",
                "Ejendomsskat",
                "Boligvedligehold",
                "Nettorente (efter fradrag)",
                "Fri cashflow",
                "Direkte investering (andel af fri cashflow)",
            ],
            "DKK/år": [
                year1_after_tax_income,
                year1_after_tax_pension,
                annual_extra_cashflow,
                -annual_living_cost,
                -annual_household_fixed,
                -annual_car_depreciation,
                -year1_property_tax,
                -year1_property_maint,
                -year1_net_interest,
                year1_free_cf,
                year1_direct_invest,
            ],
        }
    )
    cf_statement_show = cf_statement.copy()
    cf_statement_show["DKK/år"] = cf_statement_show["DKK/år"].map(fmt_dkk)
    st.dataframe(cf_statement_show, width="stretch", hide_index=True)

    lev_target = st.selectbox(
        "Gearing-mål (hvor låneprovenu investeres)",
        [
            ("ask", "ASK (hvis plads)"),
            ("private_etf", "ETF (lagerbeskatning)"),
            ("private_equity", "Aktier (realisationsbeskatning)"),
            ("holding", "Holding ApS"),
        ],
        format_func=lambda x: x[1],
    )[0]

    st.subheader("3) Lifecycle glidepath")
    g1, g2 = st.columns(2)
    with g1:
        glidepath_enabled = st.toggle("Aktivér glidepath (mere defensiv over tid)", value=True)
    with g2:
        risk_comfort = st.slider("Risikokomfort (1=lav, 10=høj)", 1, 10, 6)
    glide_shift = 0.0 if not glidepath_enabled else (11 - risk_comfort) / 10 * 0.60
    st.caption(f"Maksimalt skift fra risikofyldte aktiver til obligationer: {glide_shift*100:.1f} % over horisonten")

    st.subheader("4) Allokering og afkastforventninger")
    st.caption("ASK vælges ikke som %-andel; den fyldes automatisk op til cap før øvrig allokering.")
    st.caption(f"Kontoarkitektur (global profil): **{account_arch}**")

    alloc_a, alloc_b = st.columns(2)
    with alloc_a:
        world_share = st.slider("World/S&P andel af ikke-ASK (%)", 0, 100, 70, 1)
        pe_share = st.slider("PE andel af ikke-ASK (%)", 0, 100, 20, 1)
    with alloc_b:
        defensive_share = st.slider("Defensiv (obligationer/kontantnær) (%)", 0, 100, 10, 1)
        if account_arch == "Hybrid":
            holding_share_risky = st.slider("Holding-andel af risikobucket (%)", 0, 100, 50, 1)
        else:
            holding_share_risky = 100 if account_arch == "Holding ApS" else 0

    norm_nonask = normalize_weights(
        {
            "world": world_share,
            "pe": pe_share,
            "defensive": defensive_share,
        }
    )

    if account_arch == "Private konti":
        raw_weights = {
            "ask": 1.0,
            "private_etf": norm_nonask["world"],
            "private_equity": norm_nonask["pe"],
            "holding": 0.0,
            "bonds": norm_nonask["defensive"],
        }
    elif account_arch == "Holding ApS":
        raw_weights = {
            "ask": 1.0,
            "private_etf": 0.0,
            "private_equity": 0.0,
            "holding": norm_nonask["world"] + norm_nonask["pe"],
            "bonds": norm_nonask["defensive"],
        }
    else:
        risky = norm_nonask["world"] + norm_nonask["pe"]
        holding_part = risky * (holding_share_risky / 100)
        private_part = risky - holding_part
        raw_weights = {
            "ask": 1.0,
            "private_etf": private_part * (norm_nonask["world"] / risky) if risky > 0 else 0.0,
            "private_equity": private_part * (norm_nonask["pe"] / risky) if risky > 0 else 0.0,
            "holding": holding_part,
            "bonds": norm_nonask["defensive"],
        }

    weights = normalize_weights(raw_weights)
    ask_room = max(0.0, ask_cap - ask_funded)
    strategic_base = starting_capital + leverage_amount + home_value
    st.caption(
        f"ASK-plads: {fmt_dkk(ask_room)} | Strategisk kapitalgrundlag (likvid + bolig + LTV): {fmt_dkk(strategic_base)}"
    )
    st.caption(
        f"Normaliseret allokering: ASK {weights['ask']*100:.1f}% | ETF {weights['private_etf']*100:.1f}% | "
        f"Aktier {weights['private_equity']*100:.1f}% | Holding {weights['holding']*100:.1f}% | "
        f"Obligationer {weights['bonds']*100:.1f}%"
    )

    ret_col1, ret_col2, ret_col3 = st.columns(3)
    with ret_col1:
        world_return = st.slider("World/S&P bruttoafkast (% p.a.)", 0.0, 15.0, 7.0, 0.25) / 100
        pe_premium = st.slider("PE merafkast vs. world (%-point)", -3.0, 8.0, 2.0, 0.25) / 100
    with ret_col2:
        bond_return = st.slider("Obligationer afkast (% p.a.)", 0.0, 10.0, 3.0, 0.25) / 100
        ask_tracking_adj = st.slider("ASK tracking/omk. justering (%-point)", -1.0, 1.0, 0.0, 0.05) / 100
    with ret_col3:
        holding_alpha = st.slider("Holding alpha vs. world (%-point)", -2.0, 4.0, 0.0, 0.25) / 100

    returns = {
        "ask": world_return + ask_tracking_adj,
        "private_etf": world_return,
        "private_equity": world_return + pe_premium,
        "holding": world_return + holding_alpha,
        "bonds": bond_return,
    }

    lev_base_return = {
        "ask": returns["ask"],
        "private_etf": returns["private_etf"],
        "private_equity": returns["private_equity"],
        "holding": returns["holding"],
    }[lev_target]
    gross_interest = leverage_amount * (mortgage_rate + regime.get("rate_shift", 0.0))
    deductible_value = gross_interest * RENTEFRADRAG_TAX_VALUE
    net_interest_cost_dkk = gross_interest - deductible_value
    gross_return_dkk = leverage_amount * lev_base_return
    lev_post_tax_return, lev_note = expected_post_tax_return_for_vehicle(
        engine=engine,
        gross_return=lev_base_return,
        vehicle=lev_target,
        invested_amount=max(100_000.0, leverage_amount if leverage_amount > 0 else starting_capital),
        ask_room=ask_room,
    )
    lev_spread = lev_post_tax_return - net_rate
    if lev_spread <= 0:
        lev_guidance = "Frarådes under nuværende antagelser (negativ post-tax spread)."
    elif lev_spread < 0.015:
        lev_guidance = "Kun forsigtig gearing (typisk LTV <= 30 %) anbefales."
    elif lev_spread < 0.030:
        lev_guidance = "Moderat gearing kan overvejes (typisk LTV 30-50 %) med stresstest."
    else:
        lev_guidance = "Positivt post-tax spread; højere gearing kan overvejes med robust reservebuffer."

    score, health_warnings = assumptions_health_check(
        annual_salary=annual_salary,
        annual_living_cost=annual_living_cost,
        annual_household_fixed=annual_household_fixed,
        annual_car_depreciation=annual_car_depreciation,
        effective_income_tax=effective_income_tax,
        returns=returns,
        ltv=ltv,
        mortgage_rate=mortgage_rate,
    )
    st.subheader("5) Assumption health check")
    st.metric("Konfidensscore", f"{score}/100")
    if health_warnings:
        for warning in health_warnings:
            st.warning(warning)
    else:
        st.success("Antagelserne ligger inden for et realistisk spænd for de fleste danske husholdninger.")

    st.subheader("5b) Gearing guidance (post-tax)")
    gg1, gg2, gg3 = st.columns(3)
    gg1.metric("Forventet post-tax afkast (mål)", fmt_pct(lev_post_tax_return), lev_note)
    gg2.metric("Nettorente efter fradrag", fmt_pct(net_rate))
    gg3.metric("Post-tax spread", fmt_pct(lev_spread))
    st.caption(
        f"Beregning: Brutto renteomkostning = {fmt_dkk(gross_interest)} | "
        f"Fradragsværdi ({RENTEFRADRAG_TAX_VALUE*100:.0f}%) = {fmt_dkk(deductible_value)} | "
        f"Netto rente = {fmt_dkk(net_interest_cost_dkk)} | "
        f"Forventet bruttoafkast på gearet beløb = {fmt_dkk(gross_return_dkk)}"
    )
    if lev_spread <= 0:
        st.error(lev_guidance)
    elif lev_spread < 0.015:
        st.warning(lev_guidance)
    else:
        st.success(lev_guidance)

    st.subheader("5c) LTV-mekanik og scenariesammenligning")
    guidance_points = []
    if ask_room > 0:
        guidance_points.append(f"Fyld ASK først: mangler {fmt_dkk(ask_room)} før resten allokeres.")
    else:
        guidance_points.append("ASK er fyldt; nye bidrag fordeles automatisk på øvrige beholdere.")

    if lev_spread > 0.03 and ltv < 50:
        guidance_points.append("Post-tax spread er stærkt; overvej moderat højere LTV hvis reservekrav stadig holdes.")
    elif lev_spread <= 0:
        guidance_points.append("Undgå ekstra gearing; prioriter egenfinansieret investering eller gældsafdrag.")
    else:
        guidance_points.append("Hold gearing moderat og verificér robusthed via Monte Carlo-fanen nedenfor.")

    if weights["private_equity"] + weights["holding"] < 0.30:
        guidance_points.append("Overvej højere andel i aktier/PE hvis risikobudget tillader det og horisonten er lang.")

    for point in guidance_points:
        st.write(f"- {point}")

    sim_common = dict(
        years=years,
        starting_capital=starting_capital,
        annual_salary=annual_salary,
        effective_income_tax=effective_income_tax,
        annual_living_cost=annual_living_cost,
        annual_household_fixed=annual_household_fixed,
        annual_car_depreciation=annual_car_depreciation,
        home_value=home_value,
        property_appreciation=property_appreciation,
        property_tax_rate=property_tax_rate,
        property_maintenance_rate=property_maintenance_rate,
        annual_extra_cashflow=annual_extra_cashflow,
        returns=returns,
        ask_already_funded=ask_funded,
        ask_start_balance=ask_start_balance,
        ask_cap=ask_cap,
        leverage_amount=leverage_amount,
        mortgage_rate=mortgage_rate,
        retirement_start_year=retirement_start_year,
        phase_down_years=phase_down_years,
        salary_after_retirement_pct=salary_after_retirement_pct,
        annual_public_pension=annual_public_pension,
        annual_private_pension=annual_private_pension,
        pension_tax_rate=pension_tax_rate,
        free_cashflow_invest_share=invest_share_pct / 100,
        annual_salary_growth=regime["salary_growth"],
        inflation_rate=regime["inflation"],
        emergency_reserve_target=reserve_target,
        emergency_reserve_start=current_cash_holdings,
        glidepath_shift_to_bonds=glide_shift,
        yearly_return_volatility=0.0,
        regime_adjustments=regime,
    )

    st.markdown("**Eksempelscenarier: uden lån vs. 30% og 60% LTV**")
    st.caption(
        "Mekanik: Låneprovenu lægges ind i porteføljen ved start og forrentes derfra. "
        "Nettorente efter fradrag trækkes i årligt cashflow, og hovedstolen modregnes i nettoformuen."
    )
    ltv_examples = [0, 30, 60]
    example_rows = []
    example_paths = {}

    for ltv_example in ltv_examples:
        leverage_example = home_value * ltv_example / 100
        net_rate_example = (mortgage_rate + regime.get("rate_shift", 0.0)) * (1 - RENTEFRADRAG_TAX_VALUE)
        yearly_net_interest_example = leverage_example * net_rate_example

        lev_post_tax_example, _ = expected_post_tax_return_for_vehicle(
            engine=engine,
            gross_return=lev_base_return,
            vehicle=lev_target,
            invested_amount=max(100_000.0, leverage_example if leverage_example > 0 else starting_capital),
            ask_room=ask_room,
        )

        df_example = simulate_mixed_portfolio(
            engine=engine,
            weights=weights,
            **(sim_common | {"leverage_amount": leverage_example}),
        )
        example_paths[f"{ltv_example}% LTV"] = df_example
        final_nw_example = float(df_example["Net Worth"].iloc[-1])

        example_rows.append(
            {
                "LTV": f"{ltv_example}%",
                "Lån mod bolig": leverage_example,
                "Nettorente (år 1)": yearly_net_interest_example,
                "Post-tax spread": lev_post_tax_example - net_rate_example,
                f"Nettoformue år {years}": final_nw_example,
            }
        )

    example_df = pd.DataFrame(example_rows)
    base_nw = float(example_df.loc[example_df["LTV"] == "0%", f"Nettoformue år {years}"].iloc[0])
    example_df["Forskel vs. 0% LTV"] = example_df[f"Nettoformue år {years}"] - base_nw

    show_example = example_df.copy()
    for c in ["Lån mod bolig", "Nettorente (år 1)", f"Nettoformue år {years}", "Forskel vs. 0% LTV"]:
        show_example[c] = show_example[c].map(fmt_dkk)
    show_example["Post-tax spread"] = show_example["Post-tax spread"].map(fmt_pct)
    st.dataframe(show_example, width="stretch", hide_index=True)

    ex_fig = go.Figure()
    for label, df_example in example_paths.items():
        ex_fig.add_trace(
            go.Scatter(
                x=df_example["Year"],
                y=df_example["Net Worth"],
                mode="lines",
                name=label,
            )
        )
    ex_fig.update_layout(
        title="Nettoformue-projektion: uden lån vs. belåning",
        yaxis_title="DKK",
        height=320,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
    )
    st.plotly_chart(ex_fig, use_container_width=True)

    custom_df = simulate_mixed_portfolio(
        engine=engine,
        weights=weights,
        **sim_common,
    )

    cash_counterfactual = build_cash_counterfactual(
        years=years,
        initial_cash=current_cash_holdings + starting_capital + ask_start_balance,
        yearly_free_cashflow=custom_df["Free Cash Flow"],
        cash_rate=cash_yield,
        inflation_rate=regime["inflation"],
    )

    no_ltv_df = simulate_mixed_portfolio(
        engine=engine,
        weights=weights,
        **(sim_common | {"leverage_amount": 0.0}),
    )
    ltv50_df = simulate_mixed_portfolio(
        engine=engine,
        weights=weights,
        **(sim_common | {"leverage_amount": home_value * 0.50}),
    )

    st.subheader("📈 Nettoformue: din strategi")
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=custom_df["Year"],
        y=custom_df["Net Worth"],
        name="Nettoformue (din strategi)",
        line=dict(color="#1565C0", width=3),
    ))
    fig1.update_layout(
        height=440,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis_title="DKK",
        hovermode="x unified",
    )
    st.plotly_chart(fig1, use_container_width=True)

    st.subheader("🔍 Årlig cash-flow transparens")
    st.caption("Hvis fri cashflow er negativt, skyldes det at efter-skat indkomst + ekstra cashflow er mindre end de samlede årlige udgifter.")
    cf_fig = go.Figure()
    cf_fig.add_trace(go.Bar(name="Fri cash flow", x=custom_df["Year"], y=custom_df["Free Cash Flow"], marker_color="#00897B"))
    cf_fig.add_trace(go.Bar(name="Årlig investering", x=custom_df["Year"], y=custom_df["Yearly Investment"], marker_color="#3949AB"))
    cf_fig.add_trace(go.Scatter(name="Reserve", x=custom_df["Year"], y=custom_df["Reserve Balance"], mode="lines", line=dict(color="#F9A825", width=2)))
    cf_fig.update_layout(
        barmode="group",
        height=360,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis_title="DKK",
    )
    st.plotly_chart(cf_fig, use_container_width=True)

    st.subheader("🔎 Cashflow forklaring (år 1)")
    year1_after_tax_income = annual_salary * (1 - effective_income_tax)
    year1_property_tax = home_value * (1 + property_appreciation) * property_tax_rate
    year1_property_maint = home_value * (1 + property_appreciation) * property_maintenance_rate
    year1_net_interest = leverage_amount * (mortgage_rate + regime.get("rate_shift", 0.0)) * (1 - RENTEFRADRAG_TAX_VALUE)
    year1_free_cf = (
        year1_after_tax_income
        + annual_extra_cashflow
        - annual_living_cost
        - annual_household_fixed
        - annual_car_depreciation
        - year1_property_tax
        - year1_property_maint
        - year1_net_interest
    )
    flow_df = pd.DataFrame(
        {
            "Led": [
                "Efter-skat løn",
                "Anden netto cashflow",
                "Leveomkostninger",
                "Store faste udgifter",
                "Bilafskrivning",
                "Ejendomsskat",
                "Boligvedligehold",
                "Nettorente (efter fradrag)",
                "Fri cashflow",
            ],
            "DKK/år": [
                year1_after_tax_income,
                annual_extra_cashflow,
                -annual_living_cost,
                -annual_household_fixed,
                -annual_car_depreciation,
                -year1_property_tax,
                -year1_property_maint,
                -year1_net_interest,
                year1_free_cf,
            ],
        }
    )
    flow_df["DKK/år"] = flow_df["DKK/år"].map(lambda x: f"{x:,.0f}")
    st.dataframe(flow_df, width="stretch", hide_index=True)

    st.subheader("💵 Counterfactual: ikke investere, kun cash (inflationsjusteret)")
    st.caption("Investerede strategier vises både nominelt og inflationsjusteret (real købekraft).")

    inflation_curve = np.power(1 + regime["inflation"], custom_df["Year"].to_numpy())
    no_ltv_real = no_ltv_df["Net Worth"].to_numpy() / inflation_curve
    ltv50_real = ltv50_df["Net Worth"].to_numpy() / inflation_curve

    final_cash_real = float(cash_counterfactual["Cash Real"].iloc[-1])
    final_no_ltv_real = float(no_ltv_real[-1])
    final_ltv50_real = float(ltv50_real[-1])

    r1, r2, r3 = st.columns(3)
    r1.metric("Slutår real: Cash", fmt_dkk(final_cash_real))
    r2.metric("Slutår real: Investeret (0% LTV)", fmt_dkk(final_no_ltv_real), fmt_dkk(final_no_ltv_real - final_cash_real))
    r3.metric("Slutår real: Investeret (50% LTV)", fmt_dkk(final_ltv50_real), fmt_dkk(final_ltv50_real - final_cash_real))

    cash_fig = go.Figure()
    cash_fig.add_trace(go.Scatter(
        x=cash_counterfactual["Year"],
        y=cash_counterfactual["Cash Nominal"],
        name="Cash (nominel)",
        line=dict(color="#6D4C41", width=2),
    ))
    cash_fig.add_trace(go.Scatter(
        x=cash_counterfactual["Year"],
        y=cash_counterfactual["Cash Real"],
        name="Cash (real købekraft, inflationsjusteret)",
        line=dict(color="#8D6E63", width=2, dash="dot"),
    ))
    cash_fig.add_trace(go.Scatter(
        x=no_ltv_df["Year"],
        y=no_ltv_df["Net Worth"],
        name="Investeret (0% LTV, nominel)",
        line=dict(color="#1E88E5", width=3),
    ))
    cash_fig.add_trace(go.Scatter(
        x=no_ltv_df["Year"],
        y=no_ltv_real,
        name="Investeret (0% LTV, real)",
        line=dict(color="#1E88E5", width=2, dash="dot"),
    ))
    cash_fig.add_trace(go.Scatter(
        x=ltv50_df["Year"],
        y=ltv50_df["Net Worth"],
        name="Investeret (50% LTV, nominel)",
        line=dict(color="#2E7D32", width=3),
    ))
    cash_fig.add_trace(go.Scatter(
        x=ltv50_df["Year"],
        y=ltv50_real,
        name="Investeret (50% LTV, real)",
        line=dict(color="#2E7D32", width=2, dash="dot"),
    ))
    cash_fig.update_layout(
        height=360,
        yaxis_title="DKK",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
    )
    st.plotly_chart(cash_fig, use_container_width=True)

    st.subheader("📉 Divergens i realafkast ved forskellig årlig investeringsopsparing")
    if len(custom_df) > 1:
        baseline_set_aside = float(custom_df["Yearly Investment"].iloc[1:].mean())
    else:
        baseline_set_aside = float(custom_df["Yearly Investment"].mean())
    baseline_set_aside = max(0.0, baseline_set_aside)

    sensitivity_multipliers = [0.5, 0.75, 1.0, 1.25, 1.5]
    sensitivity_rows = []
    sensitivity_fig = go.Figure()

    for mult in sensitivity_multipliers:
        target_set_aside = baseline_set_aside * mult
        delta_cashflow = target_set_aside - baseline_set_aside
        df_sens = simulate_mixed_portfolio(
            engine=engine,
            weights=weights,
            **(sim_common | {"annual_extra_cashflow": annual_extra_cashflow + delta_cashflow}),
        )

        inflation_curve_sens = np.power(1 + regime["inflation"], df_sens["Year"].to_numpy())
        real_nw = df_sens["Net Worth"].to_numpy() / inflation_curve_sens
        start_real = max(1.0, float(real_nw[0]))
        end_real = float(real_nw[-1])
        real_cagr = (end_real / start_real) ** (1 / years) - 1 if years > 0 else 0.0

        sensitivity_fig.add_trace(
            go.Scatter(
                x=df_sens["Year"],
                y=real_nw,
                mode="lines",
                name=f"{mult:.2f}x opsparing ({fmt_dkk(target_set_aside)}/år)",
            )
        )

        sensitivity_rows.append(
            {
                "Opsparing/år (mål)": target_set_aside,
                "Multiplier": mult,
                "Slutår real nettoformue": end_real,
                "Real CAGR": real_cagr,
            }
        )

    sensitivity_df = pd.DataFrame(sensitivity_rows).sort_values("Opsparing/år (mål)")
    baseline_end_real = float(
        sensitivity_df.loc[np.isclose(sensitivity_df["Multiplier"], 1.0), "Slutår real nettoformue"].iloc[0]
    )
    sensitivity_df["Divergens vs baseline"] = sensitivity_df["Slutår real nettoformue"] - baseline_end_real

    show_sens = sensitivity_df.copy()
    show_sens["Opsparing/år (mål)"] = show_sens["Opsparing/år (mål)"].map(fmt_dkk)
    show_sens["Slutår real nettoformue"] = show_sens["Slutår real nettoformue"].map(fmt_dkk)
    show_sens["Divergens vs baseline"] = show_sens["Divergens vs baseline"].map(fmt_dkk)
    show_sens["Real CAGR"] = show_sens["Real CAGR"].map(fmt_pct)
    st.dataframe(show_sens[["Opsparing/år (mål)", "Real CAGR", "Slutår real nettoformue", "Divergens vs baseline"]], width="stretch", hide_index=True)

    sensitivity_fig.update_layout(
        title="Real nettoformue over tid ved forskellig årlig investeringsopsparing",
        yaxis_title="DKK (real købekraft)",
        height=340,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
    )
    st.plotly_chart(sensitivity_fig, use_container_width=True)

    divergence_bar = px.bar(
        sensitivity_df,
        x="Opsparing/år (mål)",
        y="Divergens vs baseline",
        title="Divergens i slutår (real) vs. baseline-opsparing",
    )
    divergence_bar.update_layout(
        yaxis_title="DKK (real)",
        xaxis_title="Årlig opsparing til investering (DKK)",
        height=300,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(divergence_bar, use_container_width=True)

    final_custom = custom_df.iloc[-1]

    k1, k2 = st.columns(2)
    k1.metric("Nettoformue (din)", fmt_dkk(final_custom["Net Worth"]))
    k2.metric("Cash real (slutår)", fmt_dkk(cash_counterfactual.iloc[-1]["Cash Real"]))

    st.subheader("📊 Porteføljesammensætning i slutåret (din)")
    final_alloc = pd.DataFrame(
        {
            "Aktiv": ["ASK", "ETF", "Aktier", "Holding", "Obligationer"],
            "Balance": [
                final_custom["ASK Balance"],
                final_custom["ETF Balance"],
                final_custom["Equity Balance"],
                final_custom["Holding Balance"],
                final_custom["Bond Balance"],
            ],
        }
    )
    if final_alloc["Balance"].sum() > 0:
        pie = px.pie(final_alloc, values="Balance", names="Aktiv", hole=0.45)
        pie.update_layout(height=350, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(pie, use_container_width=True)
    else:
        st.info("Ingen aktivbalance at vise endnu for slutåret.")

    st.subheader("📋 Slutårs-opsummering")
    summary = pd.DataFrame(
        [
            {
                "Strategi": "Din sammensætning",
                "Nettoformue": f"{final_custom['Net Worth']:,.0f}",
                "Portefølje": f"{final_custom['Portfolio Value']:,.0f}",
                "Boligværdi": f"{final_custom['Property Value']:,.0f}",
                "Skat/år (slutår)": f"{final_custom['Tax Paid']:,.0f}",
            },
        ]
    )
    st.dataframe(summary, width="stretch", hide_index=True)

    with st.expander("🧭 Husholdnings-anbefaling: sådan struktureres investeringerne", expanded=True):
        # Avoid mixing one-off deployment from existing cash (year 1) with recurring annual capacity.
        if len(custom_df) > 1:
            recurring_investment_series = custom_df["Yearly Investment"].iloc[1:]
        else:
            recurring_investment_series = custom_df["Yearly Investment"]

        annual_investment_capacity = max(0.0, float(recurring_investment_series.mean()))
        plan_rows, plan_steps, recommended_arch = build_household_structuring_plan(
            engine=engine,
            current_cash_holdings=current_cash_holdings,
            reserve_target=reserve_target,
            ask_funded=ask_funded,
            annual_investment_capacity=annual_investment_capacity,
            weights=weights,
            world_return=world_return,
            years=years,
            ask_cap=ask_cap,
        )
        st.info(f"Model-baseret anbefalet kontoarkitektur: **{recommended_arch}**")
        for step in plan_steps:
            st.write(step)
        plan_show = plan_rows.copy()
        plan_show["Beløb nu (DKK)"] = plan_show["Beløb nu (DKK)"].map(lambda v: f"{v:,.0f}")
        plan_show["Månedligt bidrag (DKK)"] = plan_show["Månedligt bidrag (DKK)"].map(lambda v: f"{v:,.0f}")
        st.dataframe(plan_show, width="stretch", hide_index=True)

    with st.expander("6) Monte Carlo (risikofordeling)", expanded=False):
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            mc_sims = st.slider("Antal simuleringer", 100, 3000, 1000, 100)
        with mc2:
            mc_vol = st.slider("Afkastvolatilitet (% p.a.)", 2.0, 30.0, 12.0, 0.5) / 100
        with mc3:
            target_net_worth = int_input_with_commas(
                "Mål nettoformue ved horisont (DKK)",
                key="sim_target_net_worth",
                min_value=100_000,
                max_value=500_000_000,
                value=15_000_000,
                step=100_000,
            )

        rp1, rp2, rp3 = st.columns(3)
        with rp1:
            p_base = st.slider("Regime sandsynlighed: Base (%)", 0, 100, 55, 1)
        with rp2:
            p_bull = st.slider("Regime sandsynlighed: Bull (%)", 0, 100, 25, 1)
        with rp3:
            p_bear = st.slider("Regime sandsynlighed: Bear (%)", 0, 100, 20, 1)

        prob_sum = max(1, p_base + p_bull + p_bear)
        regime_probs = {
            "Base": p_base / prob_sum,
            "Bull": p_bull / prob_sum,
            "Bear": p_bear / prob_sum,
        }

        mc_result = run_monte_carlo(
            engine=engine,
            simulations=mc_sims,
            regime_probs=regime_probs,
            target_net_worth=target_net_worth,
            years=years,
            starting_capital=starting_capital,
            annual_salary=annual_salary,
            effective_income_tax=effective_income_tax,
            annual_living_cost=annual_living_cost,
            annual_household_fixed=annual_household_fixed,
            annual_car_depreciation=annual_car_depreciation,
            home_value=home_value,
            property_appreciation=property_appreciation,
            property_tax_rate=property_tax_rate,
            property_maintenance_rate=property_maintenance_rate,
            annual_extra_cashflow=annual_extra_cashflow,
            weights=weights,
            returns=returns,
            ask_already_funded=ask_funded,
            ask_start_balance=ask_start_balance,
            ask_cap=ask_cap,
            leverage_amount=leverage_amount,
            mortgage_rate=mortgage_rate,
            annual_salary_growth=regime["salary_growth"],
            inflation_rate=regime["inflation"],
            emergency_reserve_target=reserve_target,
            emergency_reserve_start=current_cash_holdings,
            glidepath_shift_to_bonds=glide_shift,
            yearly_return_volatility=mc_vol,
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("P(når mål)", f"{mc_result['prob_hit_target']*100:.1f}%")
        m2.metric("P5 nettoformue", fmt_dkk(mc_result["p5"]))
        m3.metric("Median nettoformue", fmt_dkk(mc_result["p50"]))
        m4.metric("Gns. shortfall-år", f"{mc_result['mean_shortfall_years']:.1f}")

        fan = go.Figure()
        fan.add_trace(go.Scatter(x=mc_result["paths"]["Year"], y=mc_result["paths"]["P10"], name="P10", line=dict(color="#EF5350")))
        fan.add_trace(go.Scatter(x=mc_result["paths"]["Year"], y=mc_result["paths"]["P50"], name="P50", line=dict(color="#1E88E5", width=3)))
        fan.add_trace(go.Scatter(x=mc_result["paths"]["Year"], y=mc_result["paths"]["P90"], name="P90", line=dict(color="#43A047")))
        fan.update_layout(height=360, yaxis_title="DKK", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fan, use_container_width=True)

    with st.expander("7) Gældsoptimering: invester vs. afdrag", expanded=False):
        annual_extra_capacity = max(0.0, float(custom_df["Yearly Investment"].tail(3).mean()))

        # Compare apples-to-apples: expected return after tax vs net debt cost after deduction.
        invested_proxy = max(100_000.0, annual_extra_capacity)
        ask_room_margin = max(0.0, ask_cap - ask_funded)

        ask_post_tax, _ = expected_post_tax_return_for_vehicle(
            engine=engine,
            gross_return=returns["ask"],
            vehicle="ask",
            invested_amount=max(1.0, invested_proxy * max(0.0, weights.get("ask", 0.0))),
            ask_room=ask_room_margin,
        )
        etf_post_tax, _ = expected_post_tax_return_for_vehicle(
            engine=engine,
            gross_return=returns["private_etf"],
            vehicle="private_etf",
            invested_amount=max(1.0, invested_proxy * max(0.0, weights.get("private_etf", 0.0))),
            ask_room=ask_room_margin,
        )
        eq_post_tax, _ = expected_post_tax_return_for_vehicle(
            engine=engine,
            gross_return=returns["private_equity"],
            vehicle="private_equity",
            invested_amount=max(1.0, invested_proxy * max(0.0, weights.get("private_equity", 0.0))),
            ask_room=ask_room_margin,
        )
        holding_post_tax, _ = expected_post_tax_return_for_vehicle(
            engine=engine,
            gross_return=returns["holding"],
            vehicle="holding",
            invested_amount=max(1.0, invested_proxy * max(0.0, weights.get("holding", 0.0))),
            ask_room=ask_room_margin,
        )
        bond_post_tax = returns["bonds"] * (1 - KAPITALINDKOMST_POS_RATE)

        expected_portfolio_return = (
            max(0.0, weights.get("ask", 0.0)) * ask_post_tax
            + max(0.0, weights.get("private_etf", 0.0)) * etf_post_tax
            + max(0.0, weights.get("private_equity", 0.0)) * eq_post_tax
            + max(0.0, weights.get("holding", 0.0)) * holding_post_tax
            + max(0.0, weights.get("bonds", 0.0)) * bond_post_tax
        )
        debt = debt_optimization_analysis(
            annual_extra_capacity=annual_extra_capacity,
            years=years,
            expected_portfolio_return=expected_portfolio_return,
            mortgage_rate=mortgage_rate + regime.get("rate_shift", 0.0),
        )
        d1, d2, d3 = st.columns(3)
        d1.metric("Netto lånerente", fmt_pct(debt["net_mortgage_rate"]))
        d2.metric("Forventet porteføljeafkast (post-tax)", fmt_pct(expected_portfolio_return))
        d3.metric("Post-tax spread", fmt_pct(debt["spread"]))
        if debt["recommendation"] == "Invester meroverskud":
            st.success(f"Anbefaling: {debt['recommendation']} (forventet mer-værdi: {fmt_dkk(debt['value_delta'])}).")
        else:
            st.warning(f"Anbefaling: {debt['recommendation']} (forventet fordel ved afdrag: {fmt_dkk(-debt['value_delta'])}).")

    with st.expander("8) Implementeringsplan (næste 12 måneder)", expanded=False):
        plan_df = implementation_plan(
            annual_investment=annual_extra_capacity * 12,
            weights=weights,
            ask_used=ask_funded,
            ask_cap=ask_cap,
        )
        plan_df["Månedlig overførsel"] = plan_df["Månedlig overførsel"].map(lambda v: f"{v:,.0f}")
        st.dataframe(plan_df, width="stretch", hide_index=True)

    with st.expander("9) Export / Advisor pack", expanded=False):
        assumptions_df = pd.DataFrame(
            {
                "Parameter": [
                    "Regime", "Byprofil", "Horisont (år)", "Startkapital", "ASK allerede indskudt",
                    "Brutto indkomst", "Effektiv skat", "Leveomkostninger", "Reserve mål", "LTV",
                    "Kontant beholdning", "Kontant rente", "Målafkast (vægtet)", "Anbefalet kontoarkitektur", "Konfidensscore",
                ],
                "Værdi": [
                    selected_regime, city, years, starting_capital, ask_funded,
                    annual_salary, effective_income_tax, annual_living_cost, reserve_target, ltv,
                    current_cash_holdings, cash_yield, expected_portfolio_return, recommended_arch, score,
                ],
            }
        )
        advisor_summary = pd.DataFrame(
            {
                "Year": custom_df["Year"],
                "Net Worth": custom_df["Net Worth"],
                "Free Cash Flow": custom_df["Free Cash Flow"],
                "Yearly Investment": custom_df["Yearly Investment"],
                "Tax Paid": custom_df["Tax Paid"],
                "Reserve Balance": custom_df["Reserve Balance"],
                "Cash Counterfactual Nominal": cash_counterfactual["Cash Nominal"],
                "Cash Counterfactual Real": cash_counterfactual["Cash Real"],
            }
        )
        advisor_text = (
            f"Strategi: {selected_regime} | By: {city}\n"
            f"Slutformue (din): {final_custom['Net Worth']:,.0f} DKK\n"
            f"Monte Carlo P(target): {mc_result['prob_hit_target']*100:.1f}%\n"
            f"Monte Carlo P5/P50/P95: {mc_result['p5']:,.0f} / {mc_result['p50']:,.0f} / {mc_result['p95']:,.0f} DKK\n"
            f"Gældsanbefaling: {debt['recommendation']}\n"
            f"Anbefalet kontoarkitektur: {recommended_arch}\n"
            f"Cash real (slutår): {cash_counterfactual.iloc[-1]['Cash Real']:,.0f} DKK\n"
            f"Assumption score: {score}/100\n"
            f"Warnings: {'; '.join(health_warnings) if health_warnings else 'Ingen kritiske advarsler'}\n"
        )

        e1, e2, e3 = st.columns(3)
        with e1:
            st.download_button(
                "Download assumptions CSV",
                data=assumptions_df.to_csv(index=False).encode("utf-8"),
                file_name="assumptions.csv",
                mime="text/csv",
            )
        with e2:
            st.download_button(
                "Download advisor summary CSV",
                data=advisor_summary.to_csv(index=False).encode("utf-8"),
                file_name="advisor_summary.csv",
                mime="text/csv",
            )
        with e3:
            st.download_button(
                "Download advisor note TXT",
                data=advisor_text.encode("utf-8"),
                file_name="advisor_note.txt",
                mime="text/plain",
            )

    if ltv > 0:
        spread = max(returns.values()) - net_rate
        if spread <= 0:
            st.warning("Gearing er sat aktiv, men netto låneomkostning er tæt på eller over forventet afkast. Overvej lavere LTV.")
        else:
            st.success("Gearing giver positiv forventet afkast-spread under nuværende antagelser.")


# ══════════════════════════════════════════════════════════════════════
#  MODULE 3 — REAL-TIME PORTFOLIO TRACKER
# ══════════════════════════════════════════════════════════════════════

def render_portfolio_tracker(engine: DanishTaxEngine):
    """
    Live portfolio tracker with latent tax liability calculations.
    """
    st.header("📊 Porteføljetracker — Live Oversigt")
    st.markdown(
        """
        Spor dine investeringer på tværs af aktivklasser. Dashboardet viser ikke
        kun *bruttokursen*, men beregner din **sande nettoformue** ved at fratrække
        den latente skat (udskudt skat) du skylder.
        """
    )

    # ── DATA ENTRY ────────────────────────────────────────────────────
    st.subheader("📝 Likvide Aktiver (Aktier / ETF'er)")

    use_demo = st.toggle(
        "Brug demodata (eksempel-portefølje)",
        value=True,
        help="Slå fra for at indtaste dine egne positioner.",
    )

    if use_demo:
        positions = build_sample_portfolio()
        st.caption(
            "📌 Demo-portefølje aktiv. "
            "Deaktivér togglen ovenfor for at tilføje dine egne positioner."
        )
    else:
        st.markdown("**Tilføj dine likvide positioner:**")
        positions = _render_position_editor()

    # ── FETCH LIVE PRICES ─────────────────────────────────────────────
    with st.spinner("🔄 Henter live kurser via yfinance…"):
        try:
            df_portfolio = fetch_portfolio_snapshot(positions)
            data_ok = True
        except Exception as e:
            st.error(f"Kunne ikke hente live data: {e}")
            df_portfolio = pd.DataFrame()
            data_ok = False

    if data_ok and not df_portfolio.empty:
        # ── Latent Tax Calculation ────────────────────────────────────
        df_portfolio["Latent Skat (DKK)"] = df_portfolio.apply(
            lambda row: _calc_latent_tax_for_row(engine, row),
            axis=1,
        )
        df_portfolio["Sand Nettoværdi (DKK)"] = (
            df_portfolio["Market Value DKK"] - df_portfolio["Latent Skat (DKK)"]
        )

        # ── KPI Cards ─────────────────────────────────────────────────
        total_market  = df_portfolio["Market Value DKK"].sum()
        total_cost    = df_portfolio["Cost Basis DKK"].sum()
        total_latent  = df_portfolio["Latent Skat (DKK)"].sum()
        total_net_net = df_portfolio["Sand Nettoværdi (DKK)"].sum()
        total_pnl     = total_market - total_cost

        kpi_cols = st.columns(4)
        kpi_cols[0].metric(
            "Bruttoporteføljeværdi",
            fmt_dkk(total_market),
            f"{total_pnl/total_cost*100:+.1f} % urealiseret",
        )
        kpi_cols[1].metric(
            "Urealiseret P&L",
            fmt_dkk(total_pnl),
            "Siden køb",
            delta_color="normal",
        )
        kpi_cols[2].metric(
            "Latent skat (udskudt)",
            fmt_dkk(total_latent),
            "Skyldigt ved realisation",
            delta_color="inverse",
        )
        kpi_cols[3].metric(
            "✅ Sand Nettoformue",
            fmt_dkk(total_net_net),
            "Brutto − latent skat",
        )

        # ── Portfolio Breakdown Chart ─────────────────────────────────
        st.subheader("📊 Aktivallokering")
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            if df_portfolio["Market Value DKK"].sum() > 0:
                fig_pie = px.pie(
                    df_portfolio,
                    values="Market Value DKK",
                    names="Ticker",
                    title="Allokering efter aktiv (brutto)",
                    hole=0.4,
                )
                fig_pie.update_traces(textposition="inside", textinfo="percent+label")
                fig_pie.update_layout(showlegend=True, height=380,
                                       paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Ingen markedsværdi til aktivallokeringsgraf endnu.")

        with col_chart2:
            if df_portfolio["Market Value DKK"].sum() > 0:
                fig_tax_pie = px.pie(
                    df_portfolio,
                    values="Market Value DKK",
                    names="Tax Vehicle",
                    title="Allokering efter skattestruktur",
                    hole=0.4,
                )
                fig_tax_pie.update_traces(textposition="inside", textinfo="percent+label")
                fig_tax_pie.update_layout(showlegend=True, height=380,
                                           paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_tax_pie, use_container_width=True)
            else:
                st.info("Ingen markedsværdi til skatteallokeringsgraf endnu.")

        # ── Gross vs Net-Net Bar ──────────────────────────────────────
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            name  = "Bruttokursværdi",
            x     = df_portfolio["Ticker"],
            y     = df_portfolio["Market Value DKK"],
            marker_color = "#2196F3",
        ))
        fig_bar.add_trace(go.Bar(
            name  = "Sand Nettoværdi (efter latent skat)",
            x     = df_portfolio["Ticker"],
            y     = df_portfolio["Sand Nettoværdi (DKK)"],
            marker_color = "#4CAF50",
        ))
        fig_bar.update_layout(
            barmode="group",
            title="Brutto vs. Sand Nettoværdi per aktiv",
            yaxis_title="DKK",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=380,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # ── Positions Table ───────────────────────────────────────────
        st.subheader("🗂️ Positionsoversigt")
        display_cols = [
            "Ticker", "Name", "Asset Type", "Tax Vehicle",
            "Market Value DKK", "Cost Basis DKK",
            "Unrealised P&L", "P&L %",
            "Latent Skat (DKK)", "Sand Nettoværdi (DKK)",
            "Last Updated",
        ]
        available = [c for c in display_cols if c in df_portfolio.columns]

        # Format numeric columns
        df_display = df_portfolio[available].copy()
        for col in ["Market Value DKK", "Cost Basis DKK", "Unrealised P&L",
                    "Latent Skat (DKK)", "Sand Nettoværdi (DKK)"]:
            if col in df_display.columns:
                df_display[col] = df_display[col].apply(
                    lambda x: f"{x:,.0f}" if pd.notna(x) else "N/A"
                )

        st.dataframe(df_display, width="stretch", hide_index=True)

        # ── Historical Performance Chart ──────────────────────────────
        st.subheader("📈 Historisk kursudvikling")
        show_ticker = st.selectbox(
            "Vælg aktiv til historisk grafvisning:",
            options=df_portfolio["Ticker"].tolist(),
        )

        with st.spinner(f"Henter historik for {show_ticker}…"):
            hist_df = fetch_historical(show_ticker, period="5y", interval="1mo")

        if not hist_df.empty:
            fig_hist = go.Figure(go.Scatter(
                x    = hist_df["Date"],
                y    = hist_df["Close"],
                mode = "lines",
                name = show_ticker,
                line = dict(color="#2196F3", width=2),
                fill = "tozeroy",
                fillcolor = "rgba(33,150,243,0.1)",
            ))
            fig_hist.update_layout(
                title=f"{show_ticker} — månedlig kurs (5 år)",
                xaxis_title="Dato",
                yaxis_title="Kurs",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=350,
            )
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info(f"Ingen historisk data tilgængelig for {show_ticker}.")

    # ── ILLIQUID ASSETS ───────────────────────────────────────────────
    st.divider()
    st.subheader("🏠 Illikvide Aktiver (Fast Ejendom, PE, Alternativer)")

    illiq_tab1, illiq_tab2, illiq_tab3 = st.tabs(
        ["🏠 Fast Ejendom", "💼 Private Equity", "⌚ Alternativer"]
    )

    with illiq_tab1:
        _render_real_estate_tracker(engine)

    with illiq_tab2:
        _render_pe_tracker()

    with illiq_tab3:
        _render_alternatives_tracker()

    # ── TOTAL WEALTH SUMMARY ──────────────────────────────────────────
    st.divider()
    st.subheader("🏆 Samlet Formuesoversigt (Netto-Netto)")
    _render_total_wealth_summary(engine, df_portfolio if data_ok and not df_portfolio.empty else pd.DataFrame())


# ── Helper: Position Editor ───────────────────────────────────────────

def _render_position_editor() -> list[dict]:
    """Render a manual position input form."""
    st.markdown(
        "_Tilføj dine positioner. Tryk 'Genberegn' for at opdatere._"
    )

    num_positions = int_input_with_commas(
        "Antal positioner",
        key="positions_count",
        min_value=1,
        max_value=20,
        value=3,
        step=1,
    )

    positions = []
    for i in range(int(num_positions)):
        with st.expander(f"Position {i+1}", expanded=(i == 0)):
            col1, col2 = st.columns(2)
            with col1:
                ticker = st.text_input(
                    f"Ticker #{i+1}",
                    value=list(POPULAR_TICKERS.keys())[i % len(POPULAR_TICKERS)],
                    key=f"ticker_{i}",
                    help="Yahoo Finance ticker, f.eks. EUNL.DE, NOVO-B.CO, MSFT",
                )
                quantity = float_input_with_commas(
                    "Antal enheder",
                    key=f"qty_{i}",
                    min_value=0.0,
                    max_value=10_000_000.0,
                    value=100.0,
                    decimals=4,
                )
            with col2:
                cost_basis = int_input_with_commas(
                    "Kostpris samlet (DKK)",
                    key=f"cost_{i}",
                    min_value=0,
                    max_value=1_000_000_000,
                    value=100_000,
                    step=1_000,
                )
                vehicle = st.selectbox(
                    "Skattestruktur",
                    ["private_realisation", "private_lager", "ask", "holding"],
                    key=f"veh_{i}",
                    help=(
                        "private_realisation = individuelle aktier\n"
                        "private_lager = ETF'er med lagerbeskatning\n"
                        "ask = Aktiesparekonto\n"
                        "holding = Holdingselskab"
                    ),
                )
                asset_type = st.selectbox(
                    "Aktivtype",
                    ["stock", "etf", "bond", "crypto"],
                    key=f"at_{i}",
                )

            positions.append({
                "ticker":      ticker,
                "quantity":    quantity,
                "cost_basis":  cost_basis,
                "asset_type":  asset_type,
                "tax_vehicle": vehicle,
            })

    return positions


def _calc_latent_tax_for_row(engine: DanishTaxEngine, row: pd.Series) -> float:
    """
    Calculate the latent (deferred) tax liability for a single portfolio row.
    """
    unrealised_gain = row.get("Unrealised P&L", 0)
    vehicle         = row.get("Tax Vehicle", "private_realisation")

    if unrealised_gain <= 0:
        return 0.0

    if vehicle == "private_realisation":
        return engine.aktieindkomst_tax(unrealised_gain).tax_paid
    elif vehicle == "private_lager":
        # Already paid annually via lagerbeskatning → minimal latent tax
        return 0.0
    elif vehicle == "ask":
        # Already paid annually at 17 % → minimal latent tax
        return 0.0
    elif vehicle == "holding":
        # Corporate tax already paid; dividend extraction tax still pending
        after_corp = unrealised_gain * (1 - CORPORATE_TAX_RATE)
        return engine.aktieindkomst_tax(after_corp).tax_paid
    return 0.0


def _render_real_estate_tracker(engine: DanishTaxEngine):
    """Real estate position tracker."""
    col1, col2 = st.columns(2)
    with col1:
        prop_type = st.selectbox(
            "Ejendomstype",
            ["copenhagen_apartment", "copenhagen_house", "provincial_house", "summer_house"],
            format_func=lambda x: {
                "copenhagen_apartment": "Københavns lejlighed",
                "copenhagen_house": "Københavns hus",
                "provincial_house": "Provins hus",
                "summer_house": "Sommerhus",
            }.get(x, x),
        )
        purchase_price = int_input_with_commas(
            "Købspris (DKK)",
            key="re_purchase_price",
            min_value=100_000,
            max_value=50_000_000,
            value=3_500_000,
            step=100_000,
        )
    with col2:
        purchase_year = int_input_with_commas(
            "Købt år",
            key="re_purchase_year",
            min_value=1950,
            max_value=date.today().year,
            value=2015,
            step=1,
        )
        is_primary = st.toggle("Primær bolig (Parcelhusreglen)", value=True)

    prop_info = estimate_property_value(purchase_price, purchase_year, prop_type)

    r1, r2, r3 = st.columns(3)
    r1.metric("Estimeret nuværende værdi", fmt_dkk(prop_info["estimated_value_dkk"]))
    r2.metric("Kursgevinst", fmt_dkk(prop_info["estimated_gain_dkk"]),
              f"+{prop_info['appreciation_rate']*100:.1f} %/år")
    r3.metric(
        "Skat på gevinst ved salg",
        "0 DKK" if is_primary else fmt_dkk(prop_info["estimated_gain_dkk"] * 0.42),
        "Skattefri (Parcelhusreglen)" if is_primary else "Ejendomsavanceskat ~42%",
        delta_color="off" if is_primary else "inverse",
    )
    st.caption(prop_info["note"])


def _render_pe_tracker():
    """Private equity position tracker."""
    col1, col2 = st.columns(2)
    with col1:
        fund_name  = st.text_input("Fond navn", value="EQT Nexus")
        investment = int_input_with_commas(
            "Investeret beløb (DKK)",
            key="pe_investment",
            min_value=10_000,
            max_value=10_000_000,
            value=500_000,
            step=10_000,
        )
    with col2:
        inv_year = int_input_with_commas(
            "Investeringsår",
            key="pe_investment_year",
            min_value=2000,
            max_value=date.today().year,
            value=2021,
            step=1,
        )
        irr      = st.slider("Forventet netto IRR (%)", 5.0, 25.0, 12.0, 0.5) / 100

    pe_info = estimate_private_equity_value(investment, inv_year, fund_name, irr)

    r1, r2, r3 = st.columns(3)
    r1.metric("Estimeret NAV", fmt_dkk(pe_info["estimated_nav"]))
    r2.metric("Estimeret gevinst", fmt_dkk(pe_info["estimated_gain"]))
    r3.metric("Likviditet", "Illikvid", "Ingen daglig kurs")
    st.caption(pe_info["note"])


def _render_alternatives_tracker():
    """Alternative assets (watches, cars, art) tracker."""
    col1, col2 = st.columns(2)
    with col1:
        asset_name  = st.text_input("Aktiv navn", value="Rolex Submariner")
        asset_class = st.selectbox(
            "Aktivklasse", ["watch", "classic_car", "art", "wine"],
            format_func=lambda x: {
                "watch": "Luksusur", "classic_car": "Klassisk bil",
                "art": "Kunst", "wine": "Vin",
            }.get(x, x),
        )
    with col2:
        pur_price = int_input_with_commas(
            "Købspris (DKK)",
            key="alt_purchase_price",
            min_value=1_000,
            max_value=5_000_000,
            value=85_000,
            step=5_000,
        )
        pur_year = int_input_with_commas(
            "Købt år",
            key="alt_purchase_year",
            min_value=1970,
            max_value=date.today().year,
            value=2019,
            step=1,
        )

    alt_info = estimate_alternative_asset(asset_name, pur_price, pur_year, asset_class)

    r1, r2, r3 = st.columns(3)
    r1.metric("Estimeret værdi", fmt_dkk(alt_info["est_value_dkk"]))
    r2.metric("Estimeret gevinst", fmt_dkk(alt_info["est_gain_dkk"]),
              f"+{alt_info['rate']*100:.0f} %/år (estimat)")
    r3.metric("Skattebehandling", "Kapitalindkomst", alt_info["tax_treatment"])
    st.caption(alt_info["note"])


def _render_total_wealth_summary(engine: DanishTaxEngine, df_liquid: pd.DataFrame):
    """Render the master net worth summary across all asset classes."""
    # Liquid
    liquid_gross  = df_liquid["Market Value DKK"].sum() if not df_liquid.empty else 0
    liquid_latent = df_liquid["Latent Skat (DKK)"].sum() if not df_liquid.empty and "Latent Skat (DKK)" in df_liquid.columns else 0
    liquid_net    = liquid_gross - liquid_latent

    # These would come from the tracker inputs in a real session;
    # using placeholder estimates here for demonstration
    re_gross   = 0
    re_latent  = 0
    pe_gross   = 0
    alt_gross  = 0

    total_gross  = liquid_gross + re_gross + pe_gross + alt_gross
    total_latent = liquid_latent + re_latent
    total_net    = total_gross - total_latent

    if total_gross == 0:
        st.info("Tilføj positioner i Likvide Aktiver-sektionen for at se samlet formue.")
        return

    # Stacked bar
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Likvide aktiver (netto)",
        x=["Samlet Formue"],
        y=[liquid_net],
        marker_color="#2196F3",
    ))
    fig.add_trace(go.Bar(
        name="Latent skat (likvide)",
        x=["Samlet Formue"],
        y=[liquid_latent],
        marker_color="#F44336",
    ))

    fig.update_layout(
        barmode="stack",
        title="Samlet Netto-Netto Formue (ekskl. fast ejendom)",
        yaxis_title="DKK",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Bruttoformue", fmt_dkk(total_gross))
    col2.metric("Total Latent Skat", fmt_dkk(total_latent), delta_color="inverse")
    col3.metric("✅ Total Sand Nettoformue", fmt_dkk(total_net))


# ══════════════════════════════════════════════════════════════════════
#  MAIN APP ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def main():
    """
    Main function — renders the sidebar, then the selected tab.
    """
    # ── Global CSS ─────────────────────────────────────────────────────
    st.markdown(
        """
        <style>
        /* Tighten header spacing */
        h1 { margin-top: 0.5rem; }
        /* Card style for metric blocks */
        [data-testid="metric-container"] {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px;
            padding: 8px 12px;
        }
        /* Sidebar header */
        .css-1d391kg { background-color: #0f1117; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Header ─────────────────────────────────────────────────────────
    st.title("🇩🇰 Dansk Investerings Dashboard")
    st.caption(
        "Uddannelsesværktøj til dansk privatinvestor — 2026 skatteregler. "
        "Konsultér altid en certificeret skatterådgiver inden investeringsbeslutninger."
    )

    # ── Sidebar → returns configured engine ───────────────────────────
    engine = render_sidebar()

    # ── Navigation Tabs ────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "🏠  Overblik & Skatteberegner",
        "🎓  Scenario Simulator",
        "📊  Porteføljetracker",
    ])

    with tab1:
        render_overview(engine)

    with tab2:
        render_scenario_simulator(engine)

    with tab3:
        render_portfolio_tracker(engine)

    # ── Footer ─────────────────────────────────────────────────────────
    st.divider()
    st.caption(
        "⚠️ **Ansvarsfraskrivelse:** Dette dashboard er et pædagogisk hjælpeværktøj. "
        "Skatteberegningerne er forenklede modeller baseret på 2026-regler. "
        "Individuelle forhold kan ændre resultatet. Rådfør dig med en autoriseret revisor "
        "eller skatterådgiver (f.eks. BDO, PwC, KPMG) inden du træffer beslutninger. "
        "Live data fra yfinance er indicative og kan have forsinkelse."
    )


if __name__ == "__main__":
    main()
