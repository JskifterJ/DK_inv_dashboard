# 🇩🇰 Dansk Investerings Dashboard & Scenario Simulator

> **In English:** A household-first investment planning tool for Danish investors, built in Python with Streamlit (developed with Claude Code). It follows one decision chain, from gross income through effective tax, expenses and free cash flow to the Danish equity savings account (ASK), account structure and net worth.
>
> - **Tax engine** on simplified 2026 Danish rules (share-income brackets, ASK, corporate tax, interest deduction)
> - **Account structure comparison:** private accounts vs. a holding company (ApS) vs. a hybrid, with ASK filled cap-first
> - **Risk-adjusted planning:** base/bull/bear macro regimes, a glidepath from risk assets into bonds set by the investor's risk comfort, and Monte Carlo simulation of the probability of reaching the goal
> - **Leverage check:** loan-to-value and post-tax interest spread on home equity
> - **Live portfolio tracker** with historical prices and latent tax per position, plus real-estate and private-equity trackers
> - **Decision output:** a line-by-line year-one cash-flow explanation, an implementation plan and an advisor export (CSV/TXT)
>
> An educational decision tool, not tax or legal advice. The interface and the rest of this README are in Danish.

Et household-first Streamlit dashboard for danske investorer.
Fokus er at vise en konsistent beslutningskæde:

`bruttoindkomst -> effektiv skat -> udgifter -> fri cashflow -> ASK -> kontostruktur -> nettoformue`

Bygget med 2026-skatteregler (forenklet model).

---

## ▶️ Run It

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.port 8501
```

Åbner på `http://localhost:8501`

---

## 🚀 Hurtig Start

1. Aktivér miljø og installer afhængigheder:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

2. Start appen:

```bash
python -m streamlit run app.py
```

---

## 📁 Filstruktur

| Fil | Formål |
|-----|--------|
| `app.py` | Hoved-UI og household simulator |
| `tax_engine.py` | Skattemotor (2026-konstanter og beregninger) |
| `data_fetcher.py` | Live data + illikvide estimater |
| `requirements.txt` | Python-afhængigheder |

---

## 🧭 Produktlogik (Scenario Simulator)

### 1) Investorprofil
- Byprofil (København/Aarhus/anden kommune)
- Brutto husholdningsindkomst
- Automatisk effektiv skat baseret på bracket-logik
- Bolig, faste omkostninger, bilafskrivning, ekstra cashflow

### 2) Cash og reserve
- Én profil-cash saldo bruges konsekvent
- Reservepolitik trækkes direkte fra denne saldo
- Counterfactual viser kontantstrategi (nominel vs real købekraft)

### 3) ASK og kontostruktur
- ASK håndteres cap-first (ikke som fri procent-allokering)
- Toggle: `ASK er allerede fyldt`
- Udenfor ASK vælges arkitektur:
	- `Private konti`
	- `Holding ApS`
	- `Hybrid`

### 4) Afkast og risiko
- World/S&P bruges som basisantagelse for equity/ETF
- PE/holding modelleres som justeringer/premier
- Makroregimer: Base/Bull/Bear
- Monte Carlo med sandsynlighed for målopnåelse

### 5) Gearing (friværdi)
- LTV og nettorente efter rentefradrag
- Guidance baseret på post-tax spread
- Formelvisning af rente, fradragsværdi og afkastforventning

### 6) Beslutningsoutput
- Cashflow forklaring år 1 (linje-for-linje)
- Household-anbefaling med konkrete nu-beløb + månedlige bidrag
- Implementeringsplan og advisor-export (CSV/TXT)

---

## ⚙️ Tilpasning af skattesatser

Opdater konstanter i `tax_engine.py` ved regelændringer:

```python
AKTIEINDKOMST_LOW_RATE         = 0.27
AKTIEINDKOMST_HIGH_RATE        = 0.42
AKTIEINDKOMST_THRESHOLD_SINGLE = 79_400
ASK_TAX_RATE                   = 0.17
ASK_DEPOSIT_LIMIT              = 174_200
CORPORATE_TAX_RATE             = 0.22
RENTEFRADRAG_TAX_VALUE         = 0.33
```

---

## 📋 Hurtig reference (2026, forenklet)

| Skatteform | Sats |
|-----------|------|
| Aktieindkomst lav | 27 % |
| Aktieindkomst høj | 42 % |
| ASK lager | 17 % |
| Selskabsskat | 22 % |
| Rentefradrag værdi | ca. 33 % |

---

## ⚠️ Ansvarsfraskrivelse

Dashboardet er et **pædagogisk beslutningsværktøj**, ikke juridisk/skattemæssig rådgivning.
Modellerne er forenklede. Individuelle forhold kan ændre resultater markant.
Konsultér altid autoriseret revisor/skatterådgiver før reelle dispositioner.
