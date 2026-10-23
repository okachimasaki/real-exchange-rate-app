# Real Exchange Rate Explorer (IMF data)

A Streamlit app that downloads monthly CPI and exchange-rate data from the
IMF SDMX 3.0 API and computes the bilateral real exchange rate between two
countries (or the Euro area, IMF code `G163`).

## Economics

| Symbol | Definition |
|---|---|
| E_i(t) | IMF exchange rate: country *i* currency per USD (`{ISO3}.XDC_USD.PA_RT.M`) |
| S(t) | Country 2 currency per 1 unit of Country 1 currency = E2(t) / E1(t) |
| P1(t), P2(t) | Monthly CPI (`{ISO3}.CPI._T.IX.M`) |
| RER(t) | S(t) × P1(t) / P2(t) |
| RER* | Average of RER(t) over valid months in the selected sample |
| Real Index(t) | 100 × RER(t) / RER* |

- RER* is recalculated every time the start or end month changes.
- Nominal S(t) is plotted in actual currency units (not normalized).
- A Real Index above 100 means Country 1's currency is stronger in real
  terms than its sample average.
- For the United States, E(t) = 1 (USD per USD).

## Features
- Choose Country 1 and Country 2 from the IMF country list (plus Euro area).
- Data from January 1976 where available.
- Chart view: Real, Nominal, or Both (Both uses two y-axes).
- Select sample period with a month slider.
- CSV download of all observations and calculations in the selected sample.
- Data coverage table showing first/last month for each series.

## Setup (Python 3.12)

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501.

Optional: if your IMF API access needs a subscription key, set it first:
`export IMF_API_KEY=your_key`.

## Data notes
- API base: `https://api.imf.org/external/sdmx/3.0`
  (dataflows `IMF.STA:CPI` and `IMF.STA:ER`).
- IMF data can have gaps or start later than 1976. Months where any of the
  four series is missing are left blank and excluded from RER*.
- Euro area CPI/exchange rate typically starts in 1999 or later; individual
  euro members' exchange-rate series may stop at euro adoption.
- Downloads are cached for 24 hours.

## Files
- `app.py` – the Streamlit app
- `requirements.txt` – Python dependencies
- `README.md` – this file
