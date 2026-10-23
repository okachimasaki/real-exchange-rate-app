# Prompt log

- **Model:** Claude Opus 5.5 (Anthropic, claude.ai)
- **Date:** October 22, 2026

## Prompt

You are an expert Python developer and international economist. Write a complete
Streamlit app compatible with Python 3.12. Give me three complete files:
`app.py`, `requirements.txt`, and `README.md`.

**Data**
- Use the IMF SDMX 3.0 API: https://api.imf.org/external/sdmx/3.0
- Monthly CPI key: `{ISO3}.CPI._T.IX.M` (CPI dataflow)
- Monthly exchange-rate key: `{ISO3}.XDC_USD.PA_RT.M` (ER dataflow)
- The Euro area code is `G163`.
- Retrieve data from January 1976 where available.
- IMF exchange rates are local-currency units per USD. Treat the US as 1 USD per USD.
- IMF data may have gaps or limited coverage: handle missing months, empty
  responses, and failed requests gracefully, and show the user a data-coverage table.

**Economics**
- Let the user choose Country 1 and Country 2 from IMF countries plus the Euro area.
- S(t) = units of Country 2 currency per 1 unit of Country 1 currency.
  Convert from the IMF per-USD rates: S(t) = E2(t) / E1(t).
- P1(t), P2(t) = monthly CPIs. RER(t) = S(t) × P1(t) / P2(t).
- The user selects a start and end month. RER* = average of RER(t) over valid
  months in that period. Real Index(t) = 100 × RER(t) / RER*.
  Recalculate RER* whenever the dates change.
- Plot nominal S(t) in actual currency units — do not normalize it.

**Interface**
- Interactive charts (Plotly). The user chooses Real, Nominal, or Both;
  for Both, use separate y-axes.
- A CSV download button containing all observations and calculations
  (E1, E2, P1, P2, S, RER, RER*, Real Index) within the selected sample.
- Cache API calls.

**README:** explain the economics, setup steps, how to run, and data limitations.
