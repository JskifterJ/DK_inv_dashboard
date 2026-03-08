"""
╔══════════════════════════════════════════════════════════════════════╗
║           DANISH TAX ENGINE  —  2026 REGULATIONS                   ║
║           tax_engine.py                                             ║
╠══════════════════════════════════════════════════════════════════════╣
║  Covers:                                                            ║
║  • Frie Midler  (realisationsbeskatning & lagerbeskatning)          ║
║  • Aktiesparekonto / ASK  (17 % lager, 174 200 DKK deposit cap)    ║
║  • Holding ApS  (22 % selskabsskat → udbytteskat cascade)          ║
║  • VSO  (22 % provisorisk skat on retained profits)                ║
║  • Rentefradrag  (mortgage interest deduction ~33 % tax value)     ║
║  • Parcelhusreglen  (primary-home gains 100 % tax-free)            ║
╚══════════════════════════════════════════════════════════════════════╝

HOW TO ADJUST FUTURE RATES:
  All tax constants live in the CONSTANTS block below.
  Simply change the numeric value — every calculation will update
  automatically because everything is derived from those constants.

DISCLAIMER:
  This engine is a simplified educational model.
  Always consult a certified Danish tax adviser (skatterådgiver)
  before making real investment decisions.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Literal


# ══════════════════════════════════════════════════════════════════════
#  SECTION 1 — 2026 TAX CONSTANTS
#  ─────────────────────────────────────────────────────────────────────
#  Edit ONLY this section to update for future tax years.
# ══════════════════════════════════════════════════════════════════════

# ── Aktieindkomst (§ 8a Personskatteloven) ────────────────────────────
AKTIEINDKOMST_LOW_RATE        = 0.27       # 27 % on gains up to threshold
AKTIEINDKOMST_HIGH_RATE       = 0.42       # 42 % on gains above threshold
AKTIEINDKOMST_THRESHOLD_SINGLE  = 79_400   # DKK — single person (2026)
AKTIEINDKOMST_THRESHOLD_MARRIED = 158_800  # DKK — married couple combined (2026)
#   Note: If one spouse does not use their full quota, the other spouse
#   may utilise the remainder. The engine models the combined limit.

# ── Aktiesparekonto / ASK ─────────────────────────────────────────────
ASK_TAX_RATE        = 0.17                # 17 % annual lagerbeskatning
ASK_DEPOSIT_LIMIT   = 174_200             # DKK cumulative deposit cap (2026)
#   Growth inside ASK does NOT count towards the deposit cap.

# ── Kapitalindkomst  (bonds, savings interest, mortgage interest) ─────
#   Negative kapitalindkomst (mortgage interest) reduces taxable income.
#   The effective "tax value" of the deduction depends on marginal rate.
#   For most investors the relevant rate is bundskat + kommuneskat ≈ 33 %.
#   Topskat does NOT apply to NEGATIVE kapitalindkomst.
RENTEFRADRAG_TAX_VALUE = 0.33             # ~33 % tax value of interest deduction
KAPITALINDKOMST_POS_RATE = 0.42           # Approximate top rate on positive kapitalindkomst

# ── Corporate / Holding ApS ───────────────────────────────────────────
CORPORATE_TAX_RATE  = 0.22               # 22 % selskabsskat (§ 17 SEL)
#   Dividend extraction from holding → personal account:
#     subject to aktieindkomst rates (27 % / 42 %)
#   Typical annual overhead for a Danish ApS:
HOLDING_DEFAULT_ADMIN_COST = 20_000      # DKK/year (accountant + LEI + Erhvervsstyrelsen)

# ── VSO (Virksomhedsskatteordningen) ──────────────────────────────────
VSO_PROVISIONAL_RATE = 0.22              # Aconto tax while profits stay in VSO

# ── Labor / personal income (reference only) ──────────────────────────
LABOR_APPROX_MARGINAL_RATE = 0.56        # ~56 % incl. AM-bidrag (8 %), bundskat,
                                          # kommuneskat, topskat — used for comparisons

# ── Real estate ───────────────────────────────────────────────────────
PRIMARY_HOME_GAIN_TAX = 0.00             # 100 % tax-free under Parcelhusreglen
                                          # (Ejendomsavancebeskatningsloven § 8)


# ══════════════════════════════════════════════════════════════════════
#  SECTION 2 — DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class TaxResult:
    """
    Standardised return type for all tax calculations.
    Makes it easy to display results in the Streamlit UI.
    """
    gross_amount: float          = 0.0    # Pre-tax gain / income
    tax_paid:     float          = 0.0    # Total tax
    net_amount:   float          = 0.0    # Amount after tax
    effective_rate: float        = 0.0    # tax_paid / gross_amount
    notes:        list           = field(default_factory=list)  # Explanatory strings
    breakdown:    dict           = field(default_factory=dict)  # Itemised detail


# ══════════════════════════════════════════════════════════════════════
#  SECTION 3 — THE TAX ENGINE CLASS
# ══════════════════════════════════════════════════════════════════════

class DanishTaxEngine:
    """
    Central tax calculation class.

    Instantiate once with the investor's profile; call individual methods
    to compute taxes for each scenario.

    Example
    -------
    engine = DanishTaxEngine(married=False, annual_income=700_000)
    result = engine.aktieindkomst_tax(100_000)
    print(f"Tax owed: {result.tax_paid:,.0f} DKK")
    """

    def __init__(
        self,
        married: bool  = False,
        annual_income: float = 600_000,
        holding_admin_cost: float = HOLDING_DEFAULT_ADMIN_COST,
    ):
        """
        Parameters
        ----------
        married            : True if investor files jointly with a spouse.
                             This doubles the 27 % aktieindkomst bracket.
        annual_income      : Gross labor income in DKK.
                             Used for marginal-rate references.
        holding_admin_cost : Annual cost (DKK) of running a Holding ApS.
                             Typical range: 15 000–30 000 DKK/year.
        """
        self.married            = married
        self.annual_income      = annual_income
        self.holding_admin_cost = holding_admin_cost

        # Pick the correct aktieindkomst threshold
        self.ai_threshold = (
            AKTIEINDKOMST_THRESHOLD_MARRIED
            if married
            else AKTIEINDKOMST_THRESHOLD_SINGLE
        )

    # ──────────────────────────────────────────────────────────────────
    #  3A  AKTIEINDKOMST  (realisationsbeskatning)
    # ──────────────────────────────────────────────────────────────────

    def aktieindkomst_tax(self, gain: float) -> TaxResult:
        """
        Progressive tax on realised stock gains / dividends.

        Rule:  27 % on the first DKK self.ai_threshold
               42 % on anything above

        Trigger: Selling individual stocks, receiving dividends.
        NOT triggered by unrealised paper gains (that is lagerbeskatning).

        Parameters
        ----------
        gain : Realised capital gain or dividend income in DKK.
        """
        if gain <= 0:
            return TaxResult(gross_amount=gain, notes=["No gain — no tax."])

        low_portion  = min(gain, self.ai_threshold)
        high_portion = max(0.0, gain - self.ai_threshold)

        low_tax  = low_portion  * AKTIEINDKOMST_LOW_RATE
        high_tax = high_portion * AKTIEINDKOMST_HIGH_RATE
        total_tax = low_tax + high_tax

        return TaxResult(
            gross_amount   = gain,
            tax_paid       = total_tax,
            net_amount     = gain - total_tax,
            effective_rate = total_tax / gain,
            notes=[
                f"27 % bracket: {low_portion:,.0f} DKK → tax {low_tax:,.0f} DKK",
                f"42 % bracket: {high_portion:,.0f} DKK → tax {high_tax:,.0f} DKK",
                f"Threshold used: {self.ai_threshold:,.0f} DKK "
                f"({'married' if self.married else 'single'})",
            ],
            breakdown={
                "low_bracket_gain": low_portion,
                "low_bracket_tax":  low_tax,
                "high_bracket_gain": high_portion,
                "high_bracket_tax":  high_tax,
            },
        )

    # ──────────────────────────────────────────────────────────────────
    #  3B  LAGERBESKATNING  (mark-to-market annual tax)
    # ──────────────────────────────────────────────────────────────────

    def lagerbeskatning_tax(
        self,
        annual_unrealised_gain: float,
        vehicle: Literal["private_etf", "ask", "holding"] = "private_etf",
    ) -> TaxResult:
        """
        Annual tax on UNREALISED gains — paid each year regardless of selling.

        Applies to:
          • Private ETFs classified as 'investeringsselskaber'  → aktieindkomst rates
          • ASK (Aktiesparekonto)                               → flat 17 %
          • Holding ApS portfolio investments                   → 22 % selskabsskat

        The key tax-drag insight: paying tax on unrealised gains each year
        means less capital compounding, which is why ASK (17 %) often
        beats private ETFs in the 42 % bracket over long horizons.

        Parameters
        ----------
        annual_unrealised_gain : Increase in portfolio value this year (DKK).
        vehicle                : Which account type holds the investment.
        """
        if annual_unrealised_gain <= 0:
            # Losses can offset future gains in lagerbeskatning
            return TaxResult(
                gross_amount=annual_unrealised_gain,
                notes=["Loss year — can be carried forward to reduce future lager tax."],
            )

        if vehicle == "ask":
            rate = ASK_TAX_RATE
            note = "ASK lagerbeskatning at 17 %"
        elif vehicle == "holding":
            rate = CORPORATE_TAX_RATE
            note = "Holding ApS lagerbeskatning at 22 % (selskabsskat)"
        else:
            # Private ETF: aktieindkomst progressive rates apply
            return self.aktieindkomst_tax(annual_unrealised_gain)

        tax = annual_unrealised_gain * rate
        return TaxResult(
            gross_amount   = annual_unrealised_gain,
            tax_paid       = tax,
            net_amount     = annual_unrealised_gain - tax,
            effective_rate = rate,
            notes=[note],
        )

    # ──────────────────────────────────────────────────────────────────
    #  3C  RENTEFRADRAG  (mortgage interest deduction)
    # ──────────────────────────────────────────────────────────────────

    def rentefradrag(self, annual_interest_paid: float) -> TaxResult:
        """
        Tax saving from deducting mortgage interest (rentefradrag).

        How it works in Danish law:
          Mortgage interest is NEGATIVE kapitalindkomst.
          It reduces your taxable income at a rate of approximately
          bundskat (12.09 %) + kommuneskat (~25 %) = ~33 %.
          Importantly, TOPSKAT does NOT apply to negative kapitalindkomst,
          so the tax value is capped at ~33 % — even for top-rate payers.

        This is why leveraging a paid-off home and investing the proceeds
        in equities (at 7 %+ expected return) can make mathematical sense:
          • Net borrowing cost = interest × (1 − 0.33)
          • Expected equity return = 7 %+
          • Spread = equity return − net borrowing cost

        Parameters
        ----------
        annual_interest_paid : Total mortgage interest paid this year (DKK).
        """
        tax_saving       = annual_interest_paid * RENTEFRADRAG_TAX_VALUE
        net_cost         = annual_interest_paid - tax_saving

        return TaxResult(
            gross_amount   = annual_interest_paid,
            tax_paid       = -tax_saving,                  # negative = tax SAVING
            net_amount     = net_cost,
            effective_rate = RENTEFRADRAG_TAX_VALUE,
            notes=[
                f"Gross interest: {annual_interest_paid:,.0f} DKK",
                f"Tax saving (~33 % of interest): {tax_saving:,.0f} DKK",
                f"Net after-tax interest cost: {net_cost:,.0f} DKK",
                "Tax value capped at ~33 % (topskat does not apply to negative kapitalindkomst)",
            ],
        )

    # ──────────────────────────────────────────────────────────────────
    #  3D  HOLDING ApS  (full tax cascade)
    # ──────────────────────────────────────────────────────────────────

    def holding_full_cascade(
        self,
        profit_before_tax: float,
        fraction_to_extract: float = 0.0,
    ) -> TaxResult:
        """
        Model the complete tax flow through a Holding ApS.

        Flow:
          Revenue
            └─ Corporate tax 22 %  (selskabsskat)
                  └─ After-tax profit stays in holding OR
                        └─ Dividend up to personal account
                              └─ Aktieindkomst tax 27 % / 42 %

        Also deducts administrative overhead to show the TRUE cost.

        Parameters
        ----------
        profit_before_tax  : Company pre-tax profit this year (DKK).
        fraction_to_extract: 0.0–1.0 — share of after-tax profit paid out
                             as dividend to the personal account now.
                             The rest stays in the holding and compounds at
                             the corporate level (tax-efficient for growth).
        """
        if profit_before_tax <= 0:
            return TaxResult(gross_amount=profit_before_tax,
                             notes=["Loss year — no corporate tax due."])

        # Step 1: Corporate tax
        corp_tax          = profit_before_tax * CORPORATE_TAX_RATE
        after_corp_tax    = profit_before_tax - corp_tax

        # Step 2: Admin cost (accountant, LEI, Erhvervsstyrelsen annual report)
        after_admin       = after_corp_tax - self.holding_admin_cost

        # Step 3: Dividend extraction (if requested)
        retained_in_holding = after_admin * (1 - fraction_to_extract)
        dividend_gross      = after_admin * fraction_to_extract
        div_tax_result      = self.aktieindkomst_tax(dividend_gross)
        dividend_net        = div_tax_result.net_amount

        total_tax   = corp_tax + div_tax_result.tax_paid + self.holding_admin_cost
        net_in_hand = dividend_net

        return TaxResult(
            gross_amount   = profit_before_tax,
            tax_paid       = total_tax,
            net_amount     = net_in_hand,
            effective_rate = total_tax / profit_before_tax if profit_before_tax else 0,
            notes=[
                f"Corporate tax (22 %): {corp_tax:,.0f} DKK",
                f"Admin overhead: {self.holding_admin_cost:,.0f} DKK/year",
                f"Retained in holding: {retained_in_holding:,.0f} DKK",
                f"Dividend extracted: {dividend_gross:,.0f} DKK → "
                f"tax {div_tax_result.tax_paid:,.0f} DKK → "
                f"net {dividend_net:,.0f} DKK in hand",
                f"Total effective rate: {total_tax/profit_before_tax*100:.1f} %",
            ],
            breakdown={
                "corporate_tax":        corp_tax,
                "after_corporate_tax":  after_corp_tax,
                "admin_cost":           self.holding_admin_cost,
                "retained_in_holding":  retained_in_holding,
                "dividend_gross":       dividend_gross,
                "dividend_tax":         div_tax_result.tax_paid,
                "dividend_net":         dividend_net,
            },
        )

    def holding_breakeven_analysis(
        self,
        portfolio_value: float,
        annual_return: float,
    ) -> dict:
        """
        Calculate the minimum portfolio size at which a Holding ApS becomes
        more tax-efficient than private investing (lagerbeskatning, top bracket).

        The holding wins when:
          Tax saved vs. private (42 % → 22 %) > Admin cost

        Parameters
        ----------
        portfolio_value : Current portfolio value (DKK).
        annual_return   : Expected annual return as a decimal (e.g. 0.07).
        """
        annual_gain = portfolio_value * annual_return

        # Private tax (assume top bracket = 42 % — conservative)
        private_tax = annual_gain * AKTIEINDKOMST_HIGH_RATE

        # Holding tax (22 % corp + admin, no extraction this year)
        holding_tax = annual_gain * CORPORATE_TAX_RATE + self.holding_admin_cost

        tax_saving = private_tax - holding_tax

        # Break-even portfolio size: admin_cost / (rate_diff)
        rate_diff   = AKTIEINDKOMST_HIGH_RATE - CORPORATE_TAX_RATE
        breakeven   = self.holding_admin_cost / rate_diff if rate_diff > 0 else float("inf")

        return {
            "portfolio_value":     portfolio_value,
            "annual_gain":         annual_gain,
            "private_tax":         private_tax,
            "holding_tax":         holding_tax,
            "annual_tax_saving":   tax_saving,
            "holding_wins":        tax_saving > 0,
            "breakeven_portfolio": breakeven,   # DKK
            "note": (
                f"Holding ApS starts winning at portfolios above "
                f"~{breakeven:,.0f} DKK (at {annual_return*100:.0f} % return, "
                f"assuming top aktieindkomst bracket of 42 %)."
            ),
        }

    # ──────────────────────────────────────────────────────────────────
    #  3E  VSO  (Virksomhedsskatteordningen)
    # ──────────────────────────────────────────────────────────────────

    def vso_retention(self, business_profit: float) -> TaxResult:
        """
        Simplified VSO (Virksomhedsskatteordningen) model.

        Who can use VSO:
          Self-employed individuals (enkeltmandsvirksomhed, I/S) with
          active business income. NOT applicable to passive investment.

        The benefit:
          Instead of paying ~56 % personal tax immediately, you pay a
          provisional 22 % on retained profits. The remainder compounds
          inside the VSO account. When you eventually withdraw, you pay
          the full personal rate — but you have had years of compounding
          at the lower rate.

        Parameters
        ----------
        business_profit : Annual business profit before tax (DKK).
        """
        provisional_tax         = business_profit * VSO_PROVISIONAL_RATE
        retained_for_investment = business_profit - provisional_tax

        # Counterfactual: what if extracted and taxed at personal rate immediately?
        if_extracted_now_tax    = business_profit * LABOR_APPROX_MARGINAL_RATE
        annual_deferral_benefit = if_extracted_now_tax - provisional_tax

        return TaxResult(
            gross_amount   = business_profit,
            tax_paid       = provisional_tax,
            net_amount     = retained_for_investment,
            effective_rate = VSO_PROVISIONAL_RATE,
            notes=[
                f"Provisional (aconto) tax 22 %: {provisional_tax:,.0f} DKK",
                f"Available for investment inside VSO: {retained_for_investment:,.0f} DKK",
                f"If withdrawn instead (56 % marginal): {if_extracted_now_tax:,.0f} DKK tax",
                f"Annual deferral benefit: {annual_deferral_benefit:,.0f} DKK",
                "Remaining tax due upon future withdrawal from VSO.",
            ],
        )

    # ──────────────────────────────────────────────────────────────────
    #  3F  PARCELHUSREGLEN
    # ──────────────────────────────────────────────────────────────────

    def primary_home_gain(self, appreciation: float) -> TaxResult:
        """
        Primary residence appreciation is 100 % tax-free under Parcelhusreglen
        (Ejendomsavancebeskatningsloven § 8).

        Conditions (simplified):
          - Must have been your primary residence for a continuous period.
          - Applies to the plot up to ~1 400 m² in most cases.
          - Investment properties do NOT qualify — they are subject to
            ejendomsavancebeskatning at kapitalindkomst / personal rates.

        Parameters
        ----------
        appreciation : Gain on sale of primary residence (DKK).
        """
        return TaxResult(
            gross_amount   = appreciation,
            tax_paid       = 0.0,
            net_amount     = appreciation,
            effective_rate = 0.0,
            notes=[
                "100 % tax-free under Parcelhusreglen (EBL § 8).",
                "Applicable only to primary residence — not investment properties.",
            ],
        )


# ══════════════════════════════════════════════════════════════════════
#  SECTION 4 — MULTI-YEAR SCENARIO SIMULATOR ENGINE
# ══════════════════════════════════════════════════════════════════════

def simulate_scenarios(
    engine:              DanishTaxEngine,
    initial_capital:     float,
    annual_contribution: float,
    annual_return:       float,
    years:               int,
    leverage_amount:     float  = 0.0,
    mortgage_rate:       float  = 0.04,
    include_vehicles:    list   = None,
) -> pd.DataFrame:
    """
    Run a multi-decade compound-growth simulation across all tax vehicles.

    Returns a tidy DataFrame suitable for Plotly visualisation.

    Parameters
    ----------
    engine               : Configured DanishTaxEngine instance.
    initial_capital      : Starting investable capital (DKK).
    annual_contribution  : Additional savings per year (DKK).
    annual_return        : Gross expected annual return (decimal, e.g. 0.07).
    years                : Investment horizon (years).
    leverage_amount      : Extra capital borrowed against real estate (DKK).
                           0 = no leverage. Added to initial_capital, but
                           mortgage interest is deducted each year.
    mortgage_rate        : Annual interest rate on the leverage loan (decimal).
    include_vehicles     : List of vehicles to model. Defaults to all.
    """
    if include_vehicles is None:
        include_vehicles = [
            "Private Stocks\n(Realisationsbeskatning)",
            "Private ETF\n(Lagerbeskatning 27/42%)",
            "ASK\n(Lagerbeskatning 17%)",
            "Holding ApS\n(22% + Udbytteskat)",
        ]

    # Map display names → internal identifiers
    vehicle_map = {
        "Private Stocks\n(Realisationsbeskatning)": "private_realisation",
        "Private ETF\n(Lagerbeskatning 27/42%)":    "private_etf",
        "ASK\n(Lagerbeskatning 17%)":               "ask",
        "Holding ApS\n(22% + Udbytteskat)":         "holding",
    }

    all_records = []

    for display_name in include_vehicles:
        v_key = vehicle_map.get(display_name, "private_etf")

        total_invested   = initial_capital + leverage_amount
        portfolio        = total_invested
        cumulative_cost_basis = total_invested   # for realisationsbeskatning
        deferred_gain    = 0.0                   # unrealised gain for realisation vehicle

        for yr in range(1, years + 1):
            # ── Annual contribution ───────────────────────────────────
            portfolio         += annual_contribution
            cumulative_cost_basis += annual_contribution

            # ── Gross investment return ───────────────────────────────
            gross_gain = portfolio * annual_return

            # ── Tax calculation per vehicle ───────────────────────────
            if v_key == "private_realisation":
                # Individual stocks: tax only on dividends annually.
                # Capital gains deferred until sale (modelled at end).
                dividend_portion = gross_gain * 0.02 / annual_return if annual_return > 0 else 0
                div_tax = engine.aktieindkomst_tax(portfolio * 0.02).tax_paid
                annual_tax = div_tax
                deferred_gain += (gross_gain - portfolio * 0.02)  # price gain deferred

            elif v_key == "private_etf":
                # ETF: annual lagerbeskatning at aktieindkomst rates (27 %/42 %)
                annual_tax = engine.aktieindkomst_tax(gross_gain).tax_paid

            elif v_key == "ask":
                # ASK: annual lagerbeskatning at flat 17 %
                annual_tax = gross_gain * ASK_TAX_RATE

            elif v_key == "holding":
                # Holding: 22 % + admin cost each year; no extraction
                annual_tax = gross_gain * CORPORATE_TAX_RATE + engine.holding_admin_cost

            else:
                annual_tax = 0.0

            # ── Mortgage interest cost (leverage) ────────────────────
            if leverage_amount > 0:
                gross_interest = leverage_amount * mortgage_rate
                net_interest   = engine.rentefradrag(gross_interest).net_amount
            else:
                net_interest = 0.0

            # ── Update portfolio value ────────────────────────────────
            net_gain  = gross_gain - annual_tax - net_interest
            portfolio = portfolio + net_gain

            # ── Latent tax liability (udskudt skat) ──────────────────
            # "If I sold everything today, what tax would be owed?"
            total_gain_over_basis = portfolio - cumulative_cost_basis

            if v_key == "private_realisation" and deferred_gain > 0:
                latent_tax = engine.aktieindkomst_tax(deferred_gain).tax_paid
            elif v_key == "holding":
                # Corporate tax already paid; dividend extraction tax still pending
                latent_tax = engine.aktieindkomst_tax(
                    portfolio * (1 - CORPORATE_TAX_RATE)
                ).tax_paid * 0.5  # Approximation — only on unrealised holding gains
            else:
                # Lagerbeskatning vehicles: tax paid annually → minimal latent tax
                latent_tax = 0.0

            net_net_worth = portfolio - latent_tax

            all_records.append({
                "Year":                  yr,
                "Vehicle":               display_name,
                "Gross Portfolio Value": round(portfolio, 0),
                "Annual Tax Paid":       round(annual_tax, 0),
                "Net Interest Cost":     round(net_interest, 0),
                "Latent Tax Liability":  round(latent_tax, 0),
                "Net-Net Worth":         round(net_net_worth, 0),
                "Cumulative Invested":   round(cumulative_cost_basis, 0),
            })

    return pd.DataFrame(all_records)


def calculate_leverage_sensitivity(
    engine:          DanishTaxEngine,
    home_equity:     float,
    ltv_range:       list,
    equity_return:   float,
    mortgage_rate:   float,
    years:           int = 20,
) -> pd.DataFrame:
    """
    Sensitivity analysis: how does LTV (Loan-to-Value) affect 20-year
    net worth when borrowing against a home to invest in equities?

    Calculates after-tax spread = equity_return − net_mortgage_rate.

    Parameters
    ----------
    home_equity    : Current market value of paid-off home (DKK).
    ltv_range      : List of LTV ratios to test (e.g. [0.0, 0.2, 0.4, 0.6, 0.8]).
    equity_return  : Expected annual equity return (decimal).
    mortgage_rate  : Annual interest rate on realkredit loan (decimal).
    years          : Projection horizon (years).
    """
    records = []
    net_mortgage_rate = mortgage_rate * (1 - RENTEFRADRAG_TAX_VALUE)

    for ltv in ltv_range:
        loan_amount  = home_equity * ltv
        invested     = loan_amount
        spread       = equity_return - net_mortgage_rate

        # Simple future value of the leveraged spread
        fv = invested * ((1 + spread) ** years) if spread > -1 else 0
        net_benefit  = fv - loan_amount  # Profit from the leverage strategy

        records.append({
            "LTV":                ltv,
            "Loan Amount (DKK)":  round(loan_amount, 0),
            "Net Mortgage Rate":  round(net_mortgage_rate * 100, 2),
            "Equity Return":      round(equity_return * 100, 2),
            "Spread (%)":         round(spread * 100, 2),
            f"Net Benefit {years}yr": round(net_benefit, 0),
            "Makes Sense":        spread > 0,
        })

    return pd.DataFrame(records)
