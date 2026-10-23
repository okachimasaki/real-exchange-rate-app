"""
Real Exchange Rate (RER) Explorer
---------------------------------
Streamlit app that pulls monthly CPI and exchange-rate data from the IMF
SDMX 3.0 API and computes the bilateral real exchange rate between two
countries (or the Euro area).

Definitions
    S(t)   = units of Country 2 currency per 1 unit of Country 1 currency
    P1(t)  = Country 1 monthly CPI,  P2(t) = Country 2 monthly CPI
    RER(t) = S(t) * P1(t) / P2(t)
    RER*   = mean of RER(t) over valid months in the selected sample
    Real Index(t) = 100 * RER(t) / RER*

IMF exchange rates are local-currency units per USD (E_i), so
    S(t) = E2(t) / E1(t)

Run:  streamlit run app.py
"""

from __future__ import annotations

import io
import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
IMF_BASE = "https://api.imf.org/external/sdmx/3.0"
CPI_FLOW = ("IMF.STA", "CPI")   # dataflow agency, id
ER_FLOW = ("IMF.STA", "ER")
CPI_KEY = "{iso}.CPI._T.IX.M"
ER_KEY = "{iso}.XDC_USD.PA_RT.M"
START_PERIOD = "1976-01"
EURO_AREA = "G163"
TIMEOUT = 60

# Optional subscription key (some IMF API tiers require one)
_API_KEY = os.environ.get("IMF_API_KEY", "")
HEADERS_BASE = {"User-Agent": "rer-explorer/1.0"}
if _API_KEY:
    HEADERS_BASE["Ocp-Apim-Subscription-Key"] = _API_KEY

# Fallback country list used only if the IMF codelist cannot be downloaded
FALLBACK_COUNTRIES = {
    "G163": "Euro Area", "USA": "United States", "JPN": "Japan",
    "GBR": "United Kingdom", "CHN": "China", "CAN": "Canada",
    "AUS": "Australia", "CHE": "Switzerland", "KOR": "Korea, Rep. of",
    "IND": "India", "BRA": "Brazil", "MEX": "Mexico", "ZAF": "South Africa",
    "SWE": "Sweden", "NOR": "Norway", "DNK": "Denmark", "NZL": "New Zealand",
    "SGP": "Singapore", "HKG": "Hong Kong SAR", "TUR": "Türkiye",
    "ARG": "Argentina", "CHL": "Chile", "COL": "Colombia", "PER": "Peru",
    "IDN": "Indonesia", "THA": "Thailand", "MYS": "Malaysia",
    "PHL": "Philippines", "POL": "Poland", "HUN": "Hungary",
    "CZE": "Czech Republic", "ISR": "Israel", "SAU": "Saudi Arabia",
    "EGY": "Egypt", "NGA": "Nigeria", "DEU": "Germany", "FRA": "France",
    "ITA": "Italy", "ESP": "Spain", "NLD": "Netherlands",
}


# --------------------------------------------------------------------------
# IMF API helpers
# --------------------------------------------------------------------------
def _parse_period(p: str) -> pd.Timestamp | None:
    """Convert IMF period strings ('1976-M01', '1976-01', '1976M01') to month start."""
    if p is None:
        return None
    s = str(p).strip().replace("-M", "-").replace("M", "-")
    try:
        return pd.Period(s[:7], freq="M").to_timestamp()
    except Exception:
        return None


def _parse_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    cols = {c.upper(): c for c in df.columns}
    if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:
        raise ValueError("CSV missing TIME_PERIOD/OBS_VALUE")
    t = df[cols["TIME_PERIOD"]].map(_parse_period)
    v = pd.to_numeric(df[cols["OBS_VALUE"]], errors="coerce")
    s = pd.Series(v.values, index=t.values).dropna()
    s = s[~s.index.isna()]
    return s


def _parse_sdmx_json(js: dict) -> pd.Series:
    """Parse SDMX-JSON 2.0 (series-level observations)."""
    data = js.get("data", js)
    structures = data.get("structures") or [data.get("structure")]
    obs_dims = structures[0]["dimensions"]["observation"]
    time_dim = next(d for d in obs_dims if d["id"] in ("TIME_PERIOD", "TIME"))
    periods = [v.get("id") or v.get("value") for v in time_dim["values"]]

    out: dict[pd.Timestamp, float] = {}
    for ds in data.get("dataSets", []):
        for _, ser in (ds.get("series") or {}).items():
            for idx, ob in (ser.get("observations") or {}).items():
                ts = _parse_period(periods[int(idx.split(":")[0])])
                val = ob[0] if isinstance(ob, list) else ob
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    continue
                if ts is not None:
                    out[ts] = val
    return pd.Series(out, dtype="float64")


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_series(agency: str, flow: str, key: str) -> pd.Series:
    """Fetch one monthly series from the IMF SDMX 3.0 API.

    Tries CSV first, then SDMX-JSON. Returns an empty Series if nothing found.
    """
    url = f"{IMF_BASE}/data/dataflow/{agency}/{flow}/+/{key}"
    params = {"c[TIME_PERIOD]": f"ge:{START_PERIOD}"}
    attempts = [
        ("application/vnd.sdmx.data+csv;version=2.0.0", _parse_csv, "text"),
        ("application/vnd.sdmx.data+json;version=2.0.0", _parse_sdmx_json, "json"),
        ("application/json", _parse_sdmx_json, "json"),
    ]
    last_err = None
    for accept, parser, kind in attempts:
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT,
                             headers={**HEADERS_BASE, "Accept": accept})
            if r.status_code == 404:
                return pd.Series(dtype="float64")  # no data for this key
            r.raise_for_status()
            if not r.content.strip():
                continue
            s = parser(r.text if kind == "text" else r.json())
            s = s.sort_index()
            s = s[s.index >= pd.Timestamp(START_PERIOD)]
            return s[~s.index.duplicated(keep="last")]
        except Exception as e:  # try next format
            last_err = e
    if last_err:
        raise RuntimeError(f"IMF request failed for {flow} {key}: {last_err}")
    return pd.Series(dtype="float64")


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def fetch_country_list() -> dict[str, str]:
    """Return {ISO3: name} from the IMF country codelist (falls back to a static list)."""
    url = f"{IMF_BASE}/structure/codelist/IMF/CL_COUNTRY/+"
    try:
        r = requests.get(url, timeout=TIMEOUT,
                         headers={**HEADERS_BASE, "Accept": "application/json"})
        r.raise_for_status()
        js = r.json()
        cls = js.get("data", js).get("codelists", [])
        codes = cls[0]["codes"]
        out = {}
        for c in codes:
            name = c.get("name")
            if isinstance(name, dict):
                name = name.get("en") or next(iter(name.values()), c["id"])
            if not name and c.get("names"):
                name = c["names"].get("en")
            out[c["id"]] = name or c["id"]
        out.setdefault(EURO_AREA, "Euro Area")
        if len(out) > 20:
            return out
    except Exception:
        pass
    return dict(FALLBACK_COUNTRIES)


def get_cpi(iso: str) -> pd.Series:
    return fetch_series(*CPI_FLOW, CPI_KEY.format(iso=iso))


def get_lcu_per_usd(iso: str) -> pd.Series:
    """Local currency per USD. For the United States this is identically 1."""
    if iso == "USA":
        idx = pd.date_range(START_PERIOD, pd.Timestamp.today(), freq="MS")
        return pd.Series(1.0, index=idx)
    return fetch_series(*ER_FLOW, ER_KEY.format(iso=iso))


# --------------------------------------------------------------------------
# Economics
# --------------------------------------------------------------------------
def build_panel(c1: str, c2: str) -> pd.DataFrame:
    e1, e2 = get_lcu_per_usd(c1), get_lcu_per_usd(c2)
    p1, p2 = get_cpi(c1), get_cpi(c2)
    df = pd.concat({"E1_LCU_per_USD": e1, "E2_LCU_per_USD": e2,
                    "P1_CPI": p1, "P2_CPI": p2}, axis=1).sort_index()
    df.index.name = "month"
    # S(t): units of Country 2 currency per 1 unit of Country 1 currency
    df["S"] = df["E2_LCU_per_USD"] / df["E1_LCU_per_USD"]
    df["RER"] = df["S"] * df["P1_CPI"] / df["P2_CPI"]
    return df


def apply_sample(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp):
    sub = df.loc[(df.index >= start) & (df.index <= end)].copy()
    valid = sub["RER"].replace([float("inf"), -float("inf")], pd.NA).dropna()
    valid = valid[valid > 0]
    rer_star = float(valid.mean()) if len(valid) else float("nan")
    sub["RER_star"] = rer_star
    sub["Real_Index"] = 100 * sub["RER"] / rer_star
    sub["valid_month"] = sub.index.isin(valid.index)
    return sub, rer_star, len(valid)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
st.set_page_config(page_title="Real Exchange Rate Explorer", layout="wide")
st.title("Real Exchange Rate Explorer (IMF data)")
st.caption("RER(t) = S(t) × P1(t) / P2(t), where S(t) = Country 2 currency per "
           "1 unit of Country 1 currency. Source: IMF SDMX 3.0 API (CPI, ER).")

countries = fetch_country_list()
iso_list = sorted(countries, key=lambda k: (k != EURO_AREA, countries[k]))
label = lambda k: f"{countries[k]} ({k})"

with st.sidebar:
    st.header("Settings")
    c1 = st.selectbox("Country 1 (base currency)", iso_list,
                      index=iso_list.index("USA") if "USA" in iso_list else 0,
                      format_func=label)
    c2 = st.selectbox("Country 2 (quote currency)", iso_list,
                      index=iso_list.index("JPN") if "JPN" in iso_list else 1,
                      format_func=label)
    view = st.radio("Chart", ["Real", "Nominal", "Both"], index=2)

if c1 == c2:
    st.warning("Please choose two different countries.")
    st.stop()

with st.spinner("Downloading IMF data…"):
    try:
        panel = build_panel(c1, c2)
    except Exception as e:
        st.error(f"Could not retrieve IMF data: {e}")
        st.stop()

# Coverage report
cov = []
for col, name in [("E1_LCU_per_USD", f"{c1} exchange rate"),
                  ("E2_LCU_per_USD", f"{c2} exchange rate"),
                  ("P1_CPI", f"{c1} CPI"), ("P2_CPI", f"{c2} CPI")]:
    s = panel[col].dropna()
    cov.append({"series": name, "observations": len(s),
                "first": s.index.min().strftime("%Y-%m") if len(s) else "—",
                "last": s.index.max().strftime("%Y-%m") if len(s) else "—"})
missing = [r["series"] for r in cov if r["observations"] == 0]
if missing:
    st.error("No IMF data found for: " + ", ".join(missing) +
             ". Try another country pair.")
    with st.expander("Data coverage"):
        st.dataframe(pd.DataFrame(cov), hide_index=True)
    st.stop()

valid_all = panel["RER"].dropna()
if valid_all.empty:
    st.error("The four series do not overlap in any month, so RER cannot be computed.")
    st.dataframe(pd.DataFrame(cov), hide_index=True)
    st.stop()

first_m, last_m = valid_all.index.min(), valid_all.index.max()
months = pd.date_range(first_m, last_m, freq="MS")
with st.sidebar:
    start_m, end_m = st.select_slider(
        "Sample period (start – end month)",
        options=list(months), value=(months[0], months[-1]),
        format_func=lambda d: d.strftime("%Y-%m"))

sample, rer_star, n_valid = apply_sample(panel, start_m, end_m)
if n_valid == 0:
    st.warning("No valid RER observations in the selected period.")
    st.stop()

cur2_per_1 = f"{c2} currency per 1 {c1} currency"
m1, m2, m3, m4 = st.columns(4)
m1.metric("RER* (sample mean)", f"{rer_star:,.4f}")
m2.metric("Valid months", f"{n_valid}")
last_valid = sample.dropna(subset=["RER"]).iloc[-1]
m3.metric("Latest Real Index", f"{last_valid['Real_Index']:,.1f}")
m4.metric("Latest S(t)", f"{last_valid['S']:,.4f}", help=cur2_per_1)

plot_df = sample.dropna(subset=["RER", "S"], how="all")
if view == "Both":
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df["Real_Index"],
                             name="Real Index (RER*=100)"), secondary_y=False)
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df["S"],
                             name=f"Nominal S(t)", line=dict(dash="dot")),
                  secondary_y=True)
    fig.update_yaxes(title_text="Real Index (RER* = 100)", secondary_y=False)
    fig.update_yaxes(title_text=f"S(t): {cur2_per_1}", secondary_y=True)
elif view == "Real":
    fig = go.Figure(go.Scatter(x=plot_df.index, y=plot_df["Real_Index"],
                               name="Real Index"))
    fig.update_yaxes(title_text="Real Index (RER* = 100)")
else:
    fig = go.Figure(go.Scatter(x=plot_df.index, y=plot_df["S"], name="S(t)"))
    fig.update_yaxes(title_text=f"S(t): {cur2_per_1}")
if view in ("Real", "Both"):
    fig.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
fig.update_layout(height=520, hovermode="x unified",
                  title=f"{countries[c1]} vs {countries[c2]}: "
                        f"{start_m:%Y-%m} to {end_m:%Y-%m}",
                  legend=dict(orientation="h", y=-0.15))
st.plotly_chart(fig, use_container_width=True)

st.info("Real Index above 100 means Country 1's currency is stronger in real "
        "terms than its sample average (real appreciation of Country 1).")

# CSV download
out = sample.reset_index()
out["month"] = out["month"].dt.strftime("%Y-%m")
out.insert(1, "country1", c1)
out.insert(2, "country2", c2)
out = out.rename(columns={"S": f"S_{c2}_per_{c1}"})
st.download_button("Download CSV (selected sample)",
                   out.to_csv(index=False).encode("utf-8"),
                   file_name=f"rer_{c1}_{c2}_{start_m:%Y%m}_{end_m:%Y%m}.csv",
                   mime="text/csv")

with st.expander("Data table"):
    st.dataframe(out, hide_index=True, use_container_width=True)
with st.expander("Data coverage (full download)"):
    st.dataframe(pd.DataFrame(cov), hide_index=True)
    st.caption("Gaps in any of the four series leave RER blank for that month; "
               "those months are excluded from RER*.")
