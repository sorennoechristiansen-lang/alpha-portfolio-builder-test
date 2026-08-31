# Alpha Portfolio Builder – Result Portal
# Version 0.2 – 2026-08-31
#
# Purpose:
# - Present a completed Alpha Portfolio Builder result in Streamlit.
# - Reuse the same step-by-step navigation pattern as the APB input app.
# - Login uses the result user_id + access_code stored in the APB result JSON.
# - Supports two result sources:
#     1) SIMGROVA result.php endpoint (production)
#     2) Local *_Result.json files beside the app (development/testing fallback)
# - Customer-facing only: no internal Alpha scores are shown.

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import altair as alt
import pandas as pd
import requests
import streamlit as st


# ------------------------------------------------------------
# PAGE / STYLE
# ------------------------------------------------------------
st.set_page_config(
    page_title="Alpha Portfolio Builder – Result",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 3.6rem !important;
        padding-bottom: 1.2rem !important;
        max-width: 1500px !important;
    }
    h1 {
        font-size: 2rem !important;
        line-height: 1.08 !important;
        margin-top: 0 !important;
        margin-bottom: .15rem !important;
    }
    h2 {
        font-size: 1.35rem !important;
        margin-top: .2rem !important;
        margin-bottom: .45rem !important;
    }
    h3 {
        font-size: 1.08rem !important;
        margin-top: .2rem !important;
        margin-bottom: .35rem !important;
    }
    div[data-testid="stVerticalBlock"] { gap: .55rem; }
    .stButton > button {
        min-height: 2.15rem !important;
        padding-top: .25rem !important;
        padding-bottom: .25rem !important;
    }
    div[data-testid="stProgress"] {
        margin-top: -.15rem !important;
        margin-bottom: .35rem !important;
    }
    .apb-card {
        border: 1px solid rgba(49,51,63,.18);
        border-radius: 12px;
        padding: 12px 14px;
        background: rgba(250,250,250,.65);
        min-height: 88px;
    }
    .apb-kicker {
        font-size: .76rem;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: .03em;
        margin-bottom: 2px;
    }
    .apb-big {
        font-size: 1.55rem;
        line-height: 1.2;
        font-weight: 700;
    }
    .apb-subtle { color: #6b7280; font-size: .88rem; }
    .apb-good { color: #12713f; }
    .apb-warn { color: #a05b00; }
    .apb-bad { color: #a52a2a; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------
STEPS = [
    "Overview",
    "Portfolio",
    "Structure layers",
    "Sectors",
    "Industries",
    "Regions",
    "PE & analyst outlook",
    "Price target history",
    "Portfolio details",
]

RESULT_SCHEMA_MIN = "0.43"
DISCLAIMER = (
    "This portfolio is a model-generated proposal based on the submitted preferences "
    "and available market/fundamental data. It is not personal investment advice. "
    "Prices, forecasts and company data can change, and you remain responsible for "
    "your own research and investment decisions."
)


# ------------------------------------------------------------
# SMALL HELPERS
# ------------------------------------------------------------
def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def fmt_num(value: Any, decimals: int = 1, suffix: str = "") -> str:
    x = safe_float(value)
    if x is None:
        return "–"
    return f"{x:,.{decimals}f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(value: Any, decimals: int = 1, signed: bool = False) -> str:
    x = safe_float(value)
    if x is None:
        return "–"
    sign = "+" if signed and x > 0 else ""
    return f"{sign}{fmt_num(x, decimals)}%"


def fmt_money(value: Any, currency: str = "DKK", decimals: int = 0) -> str:
    x = safe_float(value)
    if x is None:
        return "–"
    return f"{fmt_num(x, decimals)} {currency}"


def fmt_date(value: Any) -> str:
    if not value:
        return "–"
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return text


def normalize(value: Any) -> str:
    return str(value or "").strip().casefold()


def result_is_valid(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("type") == "apb_result"
        and isinstance(data.get("portfolio"), dict)
        and isinstance(data.get("phase2"), dict)
        and isinstance(data.get("phase3"), dict)
    )


def local_result_files() -> List[Path]:
    root = Path.cwd()
    candidates = []
    for pattern in ("*_Result.json", "*_result.json", "APB*.json"):
        candidates.extend(root.glob(pattern))
    # De-duplicate and newest first.
    unique = {p.resolve(): p for p in candidates if p.is_file()}
    return sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def load_local_result(user_id: str, access_code: str) -> Tuple[Optional[dict], Optional[str]]:
    uid = normalize(user_id)
    code = normalize(access_code)
    for path in local_result_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not result_is_valid(data):
            continue
        if normalize(data.get("user_id")) == uid and normalize(data.get("access_code")) == code:
            return data, f"Local test file: {path.name}"
    return None, None


def streamlit_secret(name: str, default: Any = None) -> Any:
    try:
        return st.secrets[name]
    except Exception:
        return default


def load_remote_result(user_id: str, access_code: str) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """Fetch the completed APB result from SIMGROVA.

    result.php expects normal POST form fields named user_id and access_code and
    returns {"ok": true, "result": {...}} when the credentials match.
    """
    url = "https://simgrova.dk/apb_api/result.php"

    headers = {}
    secret = str(streamlit_secret("APB_SECRET", "") or "").strip()
    if secret:
        headers["X-APB-SECRET"] = secret

    try:
        response = requests.post(
            url,
            headers=headers,
            data={"user_id": user_id.strip(), "access_code": access_code.strip()},
            timeout=20,
        )
    except Exception as exc:
        return None, None, f"Could not contact the result service: {exc}"

    if response.status_code in (401, 403, 404):
        return None, None, "The ID/code was not accepted, or no completed portfolio was found."
    if response.status_code != 200:
        return None, None, f"Result service returned HTTP {response.status_code}."

    try:
        payload = response.json()
    except Exception:
        return None, None, "The result service did not return valid JSON."

    data = payload.get("result") if isinstance(payload, dict) and "result" in payload else payload
    if not result_is_valid(data):
        return None, None, "The result service returned an unsupported result format."

    if normalize(data.get("user_id")) != normalize(user_id) or normalize(data.get("access_code")) != normalize(access_code):
        return None, None, "The returned portfolio does not match the supplied login credentials."

    return data, "SIMGROVA result service", None


def authenticate(user_id: str, access_code: str) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    data, source, error = load_remote_result(user_id, access_code)
    if data is not None:
        return data, source, None
    # If a production service is configured and explicitly rejected the credentials,
    # do not silently bypass it with a local file.
    if error:
        return None, None, error

    data, source = load_local_result(user_id, access_code)
    if data is not None:
        return data, source, None

    return None, None, "No completed portfolio matched that ID and code."


def find_brand_image() -> Optional[Path]:
    for name in ("Startscreen.png", "apb_cover.png", "APB_cover.png", "cover.png"):
        p = Path(name)
        if p.exists() and p.is_file():
            return p
    return None


def card(label: str, value: str, sub: str = "") -> None:
    st.markdown(
        f"""
        <div class="apb-card">
          <div class="apb-kicker">{label}</div>
          <div class="apb-big">{value}</div>
          <div class="apb-subtle">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def dataframe_height(rows: int, max_rows: int = 18) -> int:
    return min(44 + 35 * max(1, min(rows, max_rows)), 680)


def display_table(df: pd.DataFrame, *, height: Optional[int] = None) -> None:
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=height or dataframe_height(len(df)),
    )


def distribution_df(rows: Iterable[dict]) -> pd.DataFrame:
    out = []
    for row in rows or []:
        out.append({
            "Category": row.get("category", "–"),
            "Actual %PF": safe_float(row.get("portfolio_weight_pct")),
            "Recommended %PF": safe_float(row.get("recommended_pct")),
            "Deviation pp": safe_float(row.get("deviation_pp")),
            "Positions": safe_int(row.get("positions")),
            "Avg. Base 1Y %": safe_float(row.get("average_base_1y_pct")),
        })
    return pd.DataFrame(out)


def distribution_chart(rows: Iterable[dict]) -> None:
    df = distribution_df(rows)
    if df.empty:
        st.info("No distribution data available.")
        return

    chart_df = df[["Category", "Actual %PF", "Recommended %PF"]].copy()
    chart_df["Actual %PF"] = pd.to_numeric(chart_df["Actual %PF"], errors="coerce")
    chart_df["Recommended %PF"] = pd.to_numeric(chart_df["Recommended %PF"], errors="coerce")

    # Actual allocation is shown as the filled bar. The recommended allocation is
    # shown only as a horizontal target marker at the correct Y-axis level, so it
    # is never visually added on top of the actual allocation.
    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "Category:N",
            sort=None,
            title=None,
            axis=alt.Axis(labelAngle=-90, labelLimit=140),
        )
    )

    actual = base.mark_bar(size=32).encode(
        y=alt.Y(
            "Actual %PF:Q",
            title="% of portfolio",
            scale=alt.Scale(zero=True),
        ),
        tooltip=[
            alt.Tooltip("Category:N", title="Category"),
            alt.Tooltip("Actual %PF:Q", title="Actual %PF", format=".1f"),
            alt.Tooltip("Recommended %PF:Q", title="Recommended %PF", format=".1f"),
        ],
    )

    target = base.mark_tick(size=34, thickness=3).encode(
        y=alt.Y("Recommended %PF:Q"),
        tooltip=[
            alt.Tooltip("Category:N", title="Category"),
            alt.Tooltip("Recommended %PF:Q", title="Recommended %PF", format=".1f"),
        ],
    )

    chart = (actual + target).properties(height=320).resolve_scale(y="shared")
    st.altair_chart(chart, use_container_width=True)


def show_distribution(rows: Iterable[dict], title: str, explanation: str = "") -> None:
    st.subheader(title)
    if explanation:
        st.info(explanation)
    left, right = st.columns([1.15, 1])
    with left:
        distribution_chart(rows)
    with right:
        df = distribution_df(rows)
        if not df.empty:
            df["Actual %PF"] = df["Actual %PF"].map(lambda x: fmt_pct(x) if pd.notna(x) else "–")
            df["Recommended %PF"] = df["Recommended %PF"].map(lambda x: fmt_pct(x) if pd.notna(x) else "–")
            df["Deviation pp"] = df["Deviation pp"].map(lambda x: fmt_num(x, 1) if pd.notna(x) else "–")
            df["Avg. Base 1Y %"] = df["Avg. Base 1Y %"].map(lambda x: fmt_pct(x) if pd.notna(x) else "–")
            display_table(df)


def weighted_average(positions: List[dict], field: str) -> Optional[float]:
    total_w = 0.0
    total = 0.0
    for p in positions:
        x = safe_float(p.get(field))
        w = safe_float(p.get("portfolio_weight_pct"))
        if x is None or w is None or w <= 0:
            continue
        total += x * w
        total_w += w
    return total / total_w if total_w > 0 else None


# ------------------------------------------------------------
# SESSION STATE
# ------------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "result_data" not in st.session_state:
    st.session_state.result_data = None
if "result_source" not in st.session_state:
    st.session_state.result_source = ""
if "wizard_step" not in st.session_state:
    st.session_state.wizard_step = 0


# ------------------------------------------------------------
# LOGIN
# ------------------------------------------------------------
def show_login() -> None:
    brand = find_brand_image()
    if brand is not None:
        st.image(str(brand), use_container_width=True)

    st.markdown(
        "<h2 style='text-align:center;margin-top:.25rem;'>Your Alpha Portfolio</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;color:#6b7280;'>Enter the Result ID and Code supplied when you submitted your portfolio request.</p>",
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        with st.form("result_login_form"):
            user_id = st.text_input("Result ID", placeholder="APB-XXXXXXXX")
            access_code = st.text_input("Code", type="password")
            submitted = st.form_submit_button("OPEN PORTFOLIO", type="primary", use_container_width=True)

        if submitted:
            if not user_id.strip() or not access_code.strip():
                st.error("Please enter both Result ID and Code.")
                return
            with st.spinner("Opening your portfolio..."):
                data, source, error = authenticate(user_id, access_code)
            if data is None:
                st.error(error or "Portfolio could not be opened.")
                return
            st.session_state.logged_in = True
            st.session_state.result_data = data
            st.session_state.result_source = source or ""
            st.session_state.wizard_step = 0
            st.rerun()


if not st.session_state.logged_in or not result_is_valid(st.session_state.result_data):
    show_login()
    st.stop()


# ------------------------------------------------------------
# RESULT DATA
# ------------------------------------------------------------
result: Dict[str, Any] = st.session_state.result_data
portfolio = result.get("portfolio", {})
phase2 = result.get("phase2", {})
phase3 = result.get("phase3", {})
original = result.get("original_input", {})
customer = result.get("customer", {})
positions: List[dict] = phase2.get("positions", []) if isinstance(phase2.get("positions"), list) else []
currency = str(portfolio.get("currency") or original.get("basic_rules", {}).get("currency") or "DKK")


# ------------------------------------------------------------
# HEADER / NAVIGATION
# ------------------------------------------------------------
title_col, logout_col = st.columns([6, 1])
with title_col:
    st.markdown(
        "<div style='font-size:2rem;font-weight:700;line-height:1.05;'>Alpha Portfolio Builder</div>",
        unsafe_allow_html=True,
    )
    name = str(customer.get("name") or "").strip()
    order_no = str(result.get("order_number") or "–")
    caption = f"Completed portfolio · {order_no}"
    if name:
        caption = f"{name} · {caption}"
    st.caption(caption)

with logout_col:
    if st.button("Log out", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.result_data = None
        st.session_state.result_source = ""
        st.session_state.wizard_step = 0
        st.rerun()

step = int(st.session_state.wizard_step)
step = max(0, min(step, len(STEPS) - 1))
st.session_state.wizard_step = step

st.markdown(f"**Step {step + 1} of {len(STEPS)} · {STEPS[step]}**")
st.progress((step + 1) / len(STEPS))

nav_left, nav_middle, nav_right = st.columns([1, 4, 1])
with nav_left:
    if step > 0 and st.button("← Back", use_container_width=True, key="nav_back_top"):
        st.session_state.wizard_step = step - 1
        st.rerun()
with nav_right:
    if step < len(STEPS) - 1 and st.button("Next →", type="primary", use_container_width=True, key="nav_next_top"):
        st.session_state.wizard_step = step + 1
        st.rerun()

st.markdown("<div style='height:.25rem;'></div>", unsafe_allow_html=True)


# ------------------------------------------------------------
# STEP 0 – OVERVIEW
# ------------------------------------------------------------
if step == 0:
    st.subheader("Portfolio overview")
    st.info(
        "This is the completed portfolio generated from your submitted rules and preferences. "
        "Use Next to walk through the portfolio composition and the main diversification views."
    )

    portfolio_value = sum(safe_float(p.get("position_value"), 0.0) or 0.0 for p in positions)
    cash = safe_float(portfolio.get("cash", {}).get("amount"), 0.0) or 0.0
    portfolio_value += cash
    base_avg = weighted_average(positions, "base_1y_pct")
    bear_avg = weighted_average(positions, "bear_1y_pct")
    bull_avg = weighted_average(positions, "bull_1y_pct")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Portfolio value", fmt_money(portfolio_value, currency), f"{len(positions)} positions")
    with c2:
        card("Cash", fmt_money(cash, currency), fmt_pct((cash / portfolio_value * 100) if portfolio_value else 0))
    with c3:
        card("Weighted Base 1Y", fmt_pct(base_avg), "Analyst base-case potential")
    with c4:
        card("Generated", fmt_date(result.get("generated_at")), f"Schema {result.get('schema_version', '–')}")

    st.markdown("### Analyst scenario overview")
    a1, a2, a3 = st.columns(3)
    with a1:
        card("Bear 1Y", fmt_pct(bear_avg), "Weighted across positions")
    with a2:
        card("Base 1Y", fmt_pct(base_avg), "Weighted across positions")
    with a3:
        card("Bull 1Y", fmt_pct(bull_avg), "Weighted across positions")

    st.markdown("### Allocation at a glance")
    left, right = st.columns(2)
    with left:
        st.markdown("**Structure layers**")
        distribution_chart(phase3.get("structure_layers", []))
    with right:
        st.markdown("**Sectors**")
        distribution_chart(phase3.get("sectors", []))

    st.warning(DISCLAIMER)


# ------------------------------------------------------------
# STEP 1 – PORTFOLIO
# ------------------------------------------------------------
elif step == 1:
    st.subheader("Built portfolio")
    st.info(
        "The table below is the portfolio itself. Portfolio weights and position values are based on the market data used when the portfolio was built."
    )

    rows = []
    for i, p in enumerate(sorted(positions, key=lambda x: safe_float(x.get("portfolio_weight_pct"), 0) or 0, reverse=True), start=1):
        rows.append({
            "#": i,
            "Name": p.get("name", "–"),
            "Ticker": p.get("ticker", "–"),
            "Exchange": p.get("exchange", "–"),
            "Shares": fmt_num(p.get("shares"), 0),
            "Price": fmt_num(p.get("current_price"), 2),
            "Trading ccy": p.get("trading_currency", "–"),
            "Position value": fmt_money(p.get("position_value"), currency),
            "%PF": fmt_pct(p.get("portfolio_weight_pct")),
            "1D": fmt_pct(p.get("change_1d_pct"), signed=True),
            "Structure": p.get("structure_layer", "–"),
            "Base 1Y": fmt_pct(p.get("base_1y_pct")),
        })
    display_table(pd.DataFrame(rows), height=650)

    st.markdown("### Inspect a position")
    options = [f"{p.get('ticker','–')} · {p.get('name','–')}" for p in positions]
    if options:
        chosen = st.selectbox("Position", options)
        p = positions[options.index(chosen)]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            card("Weight", fmt_pct(p.get("portfolio_weight_pct")), fmt_money(p.get("position_value"), currency))
        with c2:
            card("Bear 1Y", fmt_pct(p.get("bear_1y_pct")), f"Target {fmt_num(p.get('bear_target'), 2)}")
        with c3:
            card("Base 1Y", fmt_pct(p.get("base_1y_pct")), f"Target {fmt_num(p.get('base_target'), 2)}")
        with c4:
            card("Bull 1Y", fmt_pct(p.get("bull_1y_pct")), f"Target {fmt_num(p.get('bull_target'), 2)}")

        left, right = st.columns(2)
        with left:
            detail_rows = pd.DataFrame([
                ["Sector", p.get("sector", "–")],
                ["Industry", p.get("industry", "–")],
                ["Country / region", p.get("country_region", "–")],
                ["Structure layer", p.get("structure_layer", "–")],
                ["Days to earnings", fmt_num(p.get("days_to_earnings"), 0)],
                ["Dividend yield", fmt_pct(p.get("dividend_yield_pct"))],
            ], columns=["Market profile", "Value"])
            display_table(detail_rows, height=260)
        with right:
            fundamental_rows = pd.DataFrame([
                ["PE", fmt_num(p.get("pe"), 1)],
                ["PEG", fmt_num(p.get("peg"), 2)],
                ["Revenue growth 3Y", fmt_pct(p.get("revenue_growth_3y_pct"))],
                ["EBIT margin TTM", fmt_pct(p.get("ebit_margin_ttm_pct"))],
                ["ROIC", fmt_pct(p.get("roic_pct"))],
                ["FCF margin", fmt_pct(p.get("fcf_margin_pct"))],
                ["FCF growth 3Y", fmt_pct(p.get("fcf_growth_3y_pct"))],
                ["SMA50", fmt_num(p.get("sma50"), 2)],
            ], columns=["Fundamental / trend", "Value"])
            display_table(fundamental_rows, height=330)


# ------------------------------------------------------------
# STEP 2 – STRUCTURE
# ------------------------------------------------------------
elif step == 2:
    show_distribution(
        phase3.get("structure_layers", []),
        "Structure layers",
        "Structure layers are the portfolio's risk/growth architecture: Fundament, Vækst, Accelerator and Potentiale. The chart compares the built allocation with the requested target allocation.",
    )

    st.markdown("### What sits in each layer")
    for layer in ["Fundament", "Vækst", "Accelerator", "Potentiale"]:
        layer_positions = [p for p in positions if normalize(p.get("structure_layer")) == normalize(layer)]
        if not layer_positions:
            continue
        with st.expander(f"{layer} · {len(layer_positions)} positions", expanded=(layer == "Fundament")):
            rows = [{
                "Name": p.get("name"),
                "Ticker": p.get("ticker"),
                "%PF": fmt_pct(p.get("portfolio_weight_pct")),
                "Base 1Y": fmt_pct(p.get("base_1y_pct")),
                "Sector": p.get("sector"),
            } for p in sorted(layer_positions, key=lambda x: safe_float(x.get("portfolio_weight_pct"), 0) or 0, reverse=True)]
            display_table(pd.DataFrame(rows))


# ------------------------------------------------------------
# STEP 3 – SECTORS
# ------------------------------------------------------------
elif step == 3:
    show_distribution(
        phase3.get("sectors", []),
        "Sector distribution",
        "Actual portfolio allocation is compared with the sector targets submitted with the request. A deviation is not automatically an error; whole-share constraints and stock quality can create differences from the target.",
    )


# ------------------------------------------------------------
# STEP 4 – INDUSTRIES
# ------------------------------------------------------------
elif step == 4:
    show_distribution(
        phase3.get("industries", []),
        "Industry distribution",
        "Industries provide a finer view than sectors and help reveal concentrations that a sector-only view can hide.",
    )

    st.markdown("### Industry holdings")
    industries = sorted({str(p.get("industry") or "Unknown") for p in positions})
    selected_industry = st.selectbox("Industry", industries)
    rows = [{
        "Name": p.get("name"),
        "Ticker": p.get("ticker"),
        "%PF": fmt_pct(p.get("portfolio_weight_pct")),
        "Base 1Y": fmt_pct(p.get("base_1y_pct")),
        "Sector": p.get("sector"),
    } for p in positions if str(p.get("industry") or "Unknown") == selected_industry]
    display_table(pd.DataFrame(rows))


# ------------------------------------------------------------
# STEP 5 – REGIONS
# ------------------------------------------------------------
elif step == 5:
    show_distribution(
        phase3.get("regions", []),
        "Regional distribution",
        "The regional view compares the built portfolio with the geographic targets from the original request.",
    )


# ------------------------------------------------------------
# STEP 6 – PE + ANALYST
# ------------------------------------------------------------
elif step == 6:
    st.subheader("PE & analyst outlook")
    st.info(
        "These views complement the diversification analysis. PE buckets show valuation mix, while the Base 1Y distribution shows how much of the portfolio sits in different analyst upside ranges."
    )

    tab1, tab2 = st.tabs(["PE distribution", "Base 1Y distribution"])
    with tab1:
        show_distribution(phase3.get("pe_distribution", []), "PE distribution")
    with tab2:
        show_distribution(phase3.get("analyst_base_distribution", []), "Base 1Y distribution")

    st.markdown("### Position-level analyst scenarios")
    analyst_rows = []
    for p in sorted(positions, key=lambda x: safe_float(x.get("base_1y_pct"), -999) or -999, reverse=True):
        analyst_rows.append({
            "Name": p.get("name"),
            "Ticker": p.get("ticker"),
            "%PF": fmt_pct(p.get("portfolio_weight_pct")),
            "Bear 1Y": fmt_pct(p.get("bear_1y_pct")),
            "Base 1Y": fmt_pct(p.get("base_1y_pct")),
            "Bull 1Y": fmt_pct(p.get("bull_1y_pct")),
            "PE": fmt_num(p.get("pe"), 1),
            "PEG": fmt_num(p.get("peg"), 2),
        })
    display_table(pd.DataFrame(analyst_rows), height=610)


# ------------------------------------------------------------
# STEP 7 – TARGET HISTORY
# ------------------------------------------------------------
elif step == 7:
    st.subheader("Portfolio price target history")
    st.info(
        "This history shows how the portfolio-level Bear, Base and Bull analyst scenarios have developed across the observations included in the result file."
    )

    history = phase3.get("price_target_history", [])
    if not history:
        st.info("No price target history is available in this result.")
    else:
        df = pd.DataFrame(history)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.sort_values("date")
            chart = df.set_index("date")[[c for c in ["bear_pct", "base_pct", "bull_pct", "portfolio_pct"] if c in df.columns]]
            chart = chart.rename(columns={
                "bear_pct": "Bear %",
                "base_pct": "Base %",
                "bull_pct": "Bull %",
                "portfolio_pct": "Portfolio %",
            })
            st.line_chart(chart, use_container_width=True)

        rows = []
        for h in history:
            rows.append({
                "Date": h.get("date", "–"),
                "Bear": fmt_pct(h.get("bear_pct")),
                "Base": fmt_pct(h.get("base_pct")),
                "Bull": fmt_pct(h.get("bull_pct")),
                "Portfolio": fmt_pct(h.get("portfolio_pct")),
            })
        display_table(pd.DataFrame(rows))


# ------------------------------------------------------------
# STEP 8 – DETAILS / REQUEST
# ------------------------------------------------------------
elif step == 8:
    st.subheader("Portfolio details")
    st.info("A compact record of the request and the generated result.")

    basic = original.get("basic_rules", {}) if isinstance(original.get("basic_rules"), dict) else {}
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Order", str(result.get("order_number") or "–"), f"Result ID {result.get('user_id','–')}")
    with c2:
        card("Requested value", fmt_money(basic.get("portfolio_value"), basic.get("currency", currency)), f"Minimum position {fmt_money(basic.get('minimum_position'), basic.get('currency', currency))}")
    with c3:
        card("Positions", str(portfolio.get("position_count", len(positions))), f"Maximum requested {basic.get('maximum_number_of_stocks','–')}")
    with c4:
        card("Generated", fmt_date(result.get("generated_at")), f"Schema {result.get('schema_version','–')}")

    left, right = st.columns(2)
    with left:
        st.markdown("### Submitted priorities")
        priorities = original.get("priorities", {})
        display_table(pd.DataFrame([
            {"Priority": k, "Weight": v} for k, v in priorities.items()
        ]))

        st.markdown("### Submitted structure targets")
        structure = original.get("structure_layers", {})
        display_table(pd.DataFrame([
            {"Layer": k, "Target": fmt_pct(v)} for k, v in structure.items()
        ]))

    with right:
        st.markdown("### Customer")
        customer_rows = [
            ["Name", customer.get("name") or "–"],
            ["Skool username", customer.get("skool_username") or "–"],
            ["Order number", result.get("order_number") or "–"],
            ["Result ID", result.get("user_id") or "–"],
            ["Generated", fmt_date(result.get("generated_at"))],
        ]
        display_table(pd.DataFrame(customer_rows, columns=["Field", "Value"]), height=260)

        st.markdown("### Result source")
        st.caption(st.session_state.result_source or "Result data")

    st.warning(DISCLAIMER)
    st.success("You have reached the end of the portfolio presentation. Use Back to revisit any section.")


# ------------------------------------------------------------
# BOTTOM NAVIGATION
# ------------------------------------------------------------
st.markdown("---")
bottom_left, bottom_middle, bottom_right = st.columns([1, 4, 1])
with bottom_left:
    if step > 0 and st.button("← Back", use_container_width=True, key="nav_back_bottom"):
        st.session_state.wizard_step = step - 1
        st.rerun()
with bottom_right:
    if step < len(STEPS) - 1 and st.button("Next →", type="primary", use_container_width=True, key="nav_next_bottom"):
        st.session_state.wizard_step = step + 1
        st.rerun()
