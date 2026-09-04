# Alpha Portfolio Builder – Result Portal
# Version 0.3 – 2026-09-04
#
# Purpose:
# - Present a completed Alpha Portfolio Builder result in Streamlit.
# - Reuse the same step-by-step navigation pattern as the APB input app.
# - Login uses the result user_id + access_code stored in the APB result JSON.
# - Supports two result sources:
#     1) SIMGROVA result.php endpoint (production)
#     2) Local *_Result.json files beside the app (development/testing fallback)
# - Customer-facing only: no internal Alpha scores are shown.
# - Revision 0.3: expanded result-side guidance, input-matched disclaimer, and full PDF report download.

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape

import altair as alt
import pandas as pd
import requests
import streamlit as st

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    )
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


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
    "Alpha Portfolio Builder is an analytical and educational tool and does not provide "
    "financial, investment, tax or legal advice. Data and calculations may contain errors, "
    "delays or omissions. Always verify relevant information independently. You are solely "
    "responsible for your investment decisions, and investing involves risk, including loss of capital."
)

DISPLAY_TRANSLATIONS = {
    # Structure layers
    "Fundament": "Foundation",
    "Vækst": "Growth",
    "Vaekst": "Growth",
    "Accelerator": "Accelerator",
    "Potentiale": "Potential",
    # Common sector labels from the Danish engine output
    "Teknologi": "Technology",
    "Sundhed": "Healthcare",
    "Finans": "Financials",
    "Forbrug cyklisk": "Consumer Cyclical",
    "Industri": "Industrials",
    "Energi": "Energy",
    "Materialer": "Materials",
    "Forsyning": "Utilities",
    "Transport": "Transport",
    "Kommunikation": "Communication",
    "Forbrug defensivt": "Consumer Defensive",
    "Andre sektorer": "Other sectors",
}

def display_text(value: Any) -> Any:
    if value is None:
        return value
    return DISPLAY_TRANSLATIONS.get(str(value), value)


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
            "Category": display_text(row.get("category", "–")),
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
# RESULT-SIDE GUIDANCE / PDF REPORT
# ------------------------------------------------------------
def render_page_explanation(step: int) -> None:
    """Explain each result page as an intelligent mirror of the input journey."""
    explanations = {
        0: (
            "Understanding your completed portfolio",
            """
The overview is the bridge between the choices you submitted and the portfolio APB actually built. It is deliberately compact: before looking at individual stocks, use this page to judge whether the **portfolio as a whole** resembles the type of portfolio you asked for.

The value and cash cards describe the capital allocation in the completed result. The weighted Bear, Base and Bull figures combine the analyst scenarios of the individual positions using their portfolio weights. They are therefore **portfolio-level scenario indicators**, not forecasts of what the portfolio will actually return. The Base figure is especially useful as a common reference when comparing portfolios, while Bear and Bull help show how wide the analyst outcome range is.

The two allocation charts give the first structural check. The filled bars show what APB actually built; the small target markers show the allocation you requested. A perfect match is not always desirable or possible because APB also has to respect whole-share position sizes, stock availability, quality, diversification and the priorities from your setup. The purpose is to see whether the result is directionally consistent before you inspect the details on the following pages.
            """,
        ),
        1: (
            "Understanding the built portfolio",
            """
This page contains the actual positions produced by the build engine. **%PF** is each position's share of the total portfolio, while *Position value* translates that weight into your chosen portfolio currency. The table is sorted by portfolio weight so that the positions with the greatest influence on the result are easiest to identify.

The **Structure** column shows the role APB assigned to each stock inside the portfolio architecture: Fundamental, Growth, Accelerator or Potential. Base 1Y is the current upside or downside to the analyst base target from the market data used when the portfolio was built. The one-day move is shown only as context; it was not intended to turn the result into a short-term trading list.

Use **Inspect a position** when you want to understand why a specific holding looks different from another. The Bear, Base and Bull targets show the range of analyst scenarios, while the market-profile and fundamental fields provide some of the information behind the stock's role. No single metric should be read in isolation. A stock can be valuable to the portfolio because of its quality, structure role or diversification even when another stock has a higher analyst upside.
            """,
        ),
        2: (
            "Understanding the structure result",
            """
In the input process you chose how much of the portfolio should ideally sit in **Fundamental, Growth, Accelerator and Potential**. This page shows what happened to that intention after APB had to combine it with the rest of your rules.

The filled bar is the **actual portfolio allocation** in each layer and the marker is your **requested target**. The *Deviation pp* column is the difference in percentage points. A positive deviation means APB allocated more than requested; a negative deviation means it allocated less. This is not automatically a quality judgement. It shows where the optimization had to compromise or where stronger candidates caused the final mix to move.

The expanders underneath reveal which stocks create each layer. This is useful because two portfolios can have the same layer percentages but very different underlying risk. The structure should therefore be read both as an allocation and as a list of the specific companies carrying that allocation.
            """,
        ),
        3: (
            "Understanding the sector result",
            """
Sector targets were entered as a desired capital distribution across the broad economic areas in the APB universe. Here those targets are compared with the **sector weights actually achieved** by the finished portfolio.

A deviation can arise because APB does not fill sectors mechanically. The engine also considers stock quality, analyst expectations, structure layers, minimum position sizes, the number of positions and your relative priority for sectors. If the Sectors priority was low, larger deviations are therefore a natural consequence of giving the optimizer more freedom. If it was high, this page becomes an important check of how successfully the requested diversification could be achieved.

Sector diversification is only the first level of business diversification. A sector can still contain several very different industries, which is why the next page goes one level deeper.
            """,
        ),
        4: (
            "Understanding the industry result",
            """
Industries are the detailed business classifications inside the broader sectors. In the input setup they were **preference strengths rather than target percentages**. The result page therefore should not be read as a promise that a preferred industry receives a specific share of the portfolio.

Instead, use this page to see where the capital actually ended up and whether hidden concentrations have appeared. Several stocks may all belong to Technology, for example, but exposure across software, semiconductors and hardware can behave very differently from having most of the capital in only one of those industries.

The industry selector lets you reveal the actual holdings behind each category. This is particularly useful when one industry has a surprisingly large allocation: you can immediately see whether the concentration comes from one large position or several smaller positions.
            """,
        ),
        5: (
            "Understanding the regional result",
            """
The regional page mirrors the geographic targets from the input process. As in the setup, region means the **country or regional classification attached to the stock in the data used by APB**. It does not mean that all of the company's revenue or economic exposure comes from that region.

The actual bars and target markers show how closely the finished portfolio follows your requested geographic mix. Differences can be caused by stock availability, whole-share constraints and the optimizer choosing stronger candidates elsewhere. The higher the Regions priority was in your input, the more significant a deviation becomes when reviewing the result.

Use this view together with sectors and industries. A portfolio can look geographically diversified while still being concentrated in one business theme, or look sector-diversified while being heavily dependent on one market. The three views are intended to complement one another.
            """,
        ),
        6: (
            "Understanding valuation and analyst outlook",
            """
This page adds two lenses that were not portfolio-allocation targets in the same sense as sectors or regions. **PE distribution** shows how the portfolio is spread across valuation ranges, while the **Base 1Y distribution** shows how much capital sits in different analyst-upside ranges.

PE is useful as context but is not a universal measure of cheap or expensive. Growth companies, cyclical businesses, financials and companies with temporarily depressed earnings can naturally have very different PE levels. PEG adds growth to the valuation picture but also has limitations. These measures are therefore best used to identify extremes or concentrations rather than as automatic buy or sell signals.

The Bear, Base and Bull columns at position level show the range of analyst target scenarios. Treat them as changing external estimates, not guaranteed outcomes. The most useful information is often the combination: how much portfolio weight is attached to a stock, what valuation you are paying, and how wide the analyst scenario range is.
            """,
        ),
        7: (
            "Understanding price-target history",
            """
Price targets are snapshots of analyst expectations and can change as companies report results, guidance changes or market conditions move. This page therefore focuses on the **direction of the portfolio-level analyst scenarios over time**, not only the latest number.

If Bear, Base and Bull scenarios are all moving upward over several observations, analyst expectations are generally improving. If the current price rises faster than the targets, however, the remaining upside can still shrink even while the targets themselves are being raised. Conversely, a falling market price can make the displayed upside larger without analysts becoming more optimistic.

The history should therefore be read as supporting evidence rather than a trading signal. It is especially useful when you compare a future APB run with this one and want to see whether analyst expectations for the portfolio have strengthened or weakened.
            """,
        ),
        8: (
            "Understanding the result record",
            """
The final page is the audit trail for this APB run. It links the completed portfolio back to the **order, original portfolio rules, submitted priorities and structure targets** that produced it. This makes the result easier to review later or compare with a future build.

The priorities are shown exactly as build weights: they are relative importance settings and do not need to add to 100. The structure targets are percentages and describe the intended portfolio architecture. If a result differs from what you expected, these submitted values are the first place to check before judging the optimizer itself.

Use **Download portfolio report (PDF)** to save a portable copy of the result. The PDF contains the main portfolio table, allocation views, analyst scenarios, history and the submitted settings available in this result file. Because market and analyst data change, the generation date is an important part of the report and should always be kept with the portfolio.
            """,
        ),
    }
    title, body = explanations.get(step, ("Understanding this result", ""))
    st.markdown(f"### {title}")
    st.markdown(body)


def _pdf_text(value: Any) -> str:
    if value is None or value == "":
        return "–"
    return escape(str(value))


def _pdf_paragraph(value: Any, style) -> Paragraph:
    return Paragraph(_pdf_text(value), style)


def build_portfolio_report_pdf(result: Dict[str, Any]) -> Optional[bytes]:
    """Create a customer-facing PDF containing the complete APB result."""
    if not REPORTLAB_AVAILABLE:
        return None

    portfolio = result.get("portfolio", {}) if isinstance(result.get("portfolio"), dict) else {}
    phase2 = result.get("phase2", {}) if isinstance(result.get("phase2"), dict) else {}
    phase3 = result.get("phase3", {}) if isinstance(result.get("phase3"), dict) else {}
    original = result.get("original_input", {}) if isinstance(result.get("original_input"), dict) else {}
    customer = result.get("customer", {}) if isinstance(result.get("customer"), dict) else {}
    positions = phase2.get("positions", []) if isinstance(phase2.get("positions"), list) else []
    basic = original.get("basic_rules", {}) if isinstance(original.get("basic_rules"), dict) else {}
    currency = str(portfolio.get("currency") or basic.get("currency") or "DKK")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=13 * mm,
        leftMargin=13 * mm,
        topMargin=13 * mm,
        bottomMargin=14 * mm,
        title="Alpha Portfolio Builder – Portfolio Report",
        author="Alpha Portfolio Builder",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="APBTitle", parent=styles["Title"], fontSize=20, leading=23, alignment=TA_CENTER, spaceAfter=5*mm))
    styles.add(ParagraphStyle(name="APBSub", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, spaceAfter=5*mm))
    styles.add(ParagraphStyle(name="APBH1", parent=styles["Heading1"], fontSize=14, leading=17, spaceBefore=3*mm, spaceAfter=2*mm))
    styles.add(ParagraphStyle(name="APBH2", parent=styles["Heading2"], fontSize=11, leading=14, spaceBefore=2.5*mm, spaceAfter=1.5*mm))
    styles.add(ParagraphStyle(name="APBBody", parent=styles["BodyText"], fontSize=8.3, leading=11, spaceAfter=2*mm))
    styles.add(ParagraphStyle(name="APBSmall", parent=styles["BodyText"], fontSize=7.2, leading=9, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="APBCell", parent=styles["BodyText"], fontSize=6.7, leading=8.2))

    story = []
    story.append(Paragraph("Alpha Portfolio Builder", styles["APBTitle"]))
    story.append(Paragraph("Portfolio Report", styles["APBTitle"]))
    name = str(customer.get("name") or "").strip()
    meta = f"Order {result.get('order_number','–')} · Generated {fmt_date(result.get('generated_at'))}"
    if name:
        meta = f"{_pdf_text(name)} · {meta}"
    story.append(Paragraph(meta, styles["APBSub"]))

    total = sum(safe_float(p.get("position_value"), 0.0) or 0.0 for p in positions)
    cash = safe_float(portfolio.get("cash", {}).get("amount"), 0.0) or 0.0
    total += cash
    summary_data = [
        ["Portfolio value", fmt_money(total, currency), "Positions", str(len(positions))],
        ["Cash", fmt_money(cash, currency), "Weighted Base 1Y", fmt_pct(weighted_average(positions, "base_1y_pct"))],
        ["Weighted Bear 1Y", fmt_pct(weighted_average(positions, "bear_1y_pct")), "Weighted Bull 1Y", fmt_pct(weighted_average(positions, "bull_1y_pct"))],
    ]
    t=Table(summary_data, colWidths=[31*mm, 45*mm, 34*mm, 47*mm])
    t.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#cfd4da")),
        ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#f2f4f7")),
        ("BACKGROUND",(2,0),(2,-1),colors.HexColor("#f2f4f7")),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),("FONTSIZE",(0,0),(-1,-1),8),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))
    story += [t, Spacer(1,4*mm)]

    story.append(Paragraph("Built portfolio", styles["APBH1"]))
    pos_header=["Name","Ticker","Shares","%PF","Structure","Sector","Base 1Y","PE"]
    pos_rows=[pos_header]
    for p in sorted(positions, key=lambda x: safe_float(x.get("portfolio_weight_pct"),0) or 0, reverse=True):
        pos_rows.append([
            _pdf_paragraph(p.get("name","–"), styles["APBCell"]), _pdf_text(p.get("ticker","–")), fmt_num(p.get("shares"),0),
            fmt_pct(p.get("portfolio_weight_pct")), _pdf_text(display_text(p.get("structure_layer","–"))),
            _pdf_paragraph(display_text(p.get("sector","–")), styles["APBCell"]), fmt_pct(p.get("base_1y_pct")), fmt_num(p.get("pe"),1),
        ])
    pt=Table(pos_rows, repeatRows=1, colWidths=[36*mm,18*mm,14*mm,15*mm,23*mm,30*mm,20*mm,13*mm])
    pt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef5")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.2,colors.HexColor("#cfd4da")),("FONTSIZE",(0,0),(-1,-1),6.6),
        ("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),2.5),("RIGHTPADDING",(0,0),(-1,-1),2.5),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    story += [pt, PageBreak()]

    def add_distribution(title, rows):
        story.append(Paragraph(title, styles["APBH1"]))
        data=[["Category","Actual %PF","Recommended %PF","Deviation pp","Positions","Avg. Base 1Y"]]
        for r in rows or []:
            data.append([
                _pdf_paragraph(display_text(r.get("category","–")), styles["APBCell"]), fmt_pct(r.get("portfolio_weight_pct")),
                fmt_pct(r.get("recommended_pct")), fmt_num(r.get("deviation_pp"),1), str(safe_int(r.get("positions"))), fmt_pct(r.get("average_base_1y_pct")),
            ])
        if len(data)==1:
            story.append(Paragraph("No distribution data available.", styles["APBBody"]))
            return
        tb=Table(data, repeatRows=1, colWidths=[48*mm,24*mm,30*mm,24*mm,20*mm,28*mm])
        tb.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef5")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("GRID",(0,0),(-1,-1),0.2,colors.HexColor("#cfd4da")),("FONTSIZE",(0,0),(-1,-1),7),
            ("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        story.append(tb)
        story.append(Spacer(1,3*mm))

    add_distribution("Structure layers", phase3.get("structure_layers", []))
    add_distribution("Sectors", phase3.get("sectors", []))
    add_distribution("Industries", phase3.get("industries", []))
    story.append(PageBreak())
    add_distribution("Regions", phase3.get("regions", []))
    add_distribution("PE distribution", phase3.get("pe_distribution", []))
    add_distribution("Base 1Y distribution", phase3.get("analyst_base_distribution", []))

    story.append(PageBreak())
    story.append(Paragraph("Position-level analyst scenarios", styles["APBH1"]))
    analyst=[["Name","Ticker","%PF","Bear 1Y","Base 1Y","Bull 1Y","PE","PEG"]]
    for p in sorted(positions, key=lambda x: safe_float(x.get("base_1y_pct"),-999) or -999, reverse=True):
        analyst.append([
            _pdf_paragraph(p.get("name","–"), styles["APBCell"]), _pdf_text(p.get("ticker","–")), fmt_pct(p.get("portfolio_weight_pct")),
            fmt_pct(p.get("bear_1y_pct")), fmt_pct(p.get("base_1y_pct")), fmt_pct(p.get("bull_1y_pct")), fmt_num(p.get("pe"),1), fmt_num(p.get("peg"),2),
        ])
    at=Table(analyst, repeatRows=1, colWidths=[42*mm,18*mm,17*mm,20*mm,20*mm,20*mm,15*mm,15*mm])
    at.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef5")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.2,colors.HexColor("#cfd4da")),("FONTSIZE",(0,0),(-1,-1),6.7),
        ("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),2.5),("RIGHTPADDING",(0,0),(-1,-1),2.5),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    story.append(at)

    history=phase3.get("price_target_history", []) if isinstance(phase3.get("price_target_history"), list) else []
    if history:
        story.append(PageBreak())
        story.append(Paragraph("Portfolio price target history", styles["APBH1"]))
        hd=[["Date","Bear","Base","Bull","Portfolio"]]
        for h in history:
            hd.append([_pdf_text(h.get("date","–")),fmt_pct(h.get("bear_pct")),fmt_pct(h.get("base_pct")),fmt_pct(h.get("bull_pct")),fmt_pct(h.get("portfolio_pct"))])
        ht=Table(hd, repeatRows=1, colWidths=[42*mm,30*mm,30*mm,30*mm,30*mm])
        ht.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef5")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("GRID",(0,0),(-1,-1),0.2,colors.HexColor("#cfd4da")),("FONTSIZE",(0,0),(-1,-1),7.2),
            ("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ]))
        story.append(ht)

    story.append(PageBreak())
    story.append(Paragraph("Submitted setup", styles["APBH1"]))
    setup=[
        ["Portfolio currency", basic.get("currency", currency)],
        ["Requested portfolio value", fmt_money(basic.get("portfolio_value"), basic.get("currency",currency))],
        ["Minimum position", fmt_money(basic.get("minimum_position"), basic.get("currency",currency))],
        ["Maximum different stocks", basic.get("maximum_number_of_stocks","–")],
        ["Minimum stocks per selected sector", basic.get("minimum_stocks_per_sector","–")],
    ]
    stbl=Table(setup, colWidths=[64*mm,98*mm])
    stbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#f2f4f7")),("GRID",(0,0),(-1,-1),0.2,colors.HexColor("#cfd4da")),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))
    story.append(stbl)

    priorities=original.get("priorities", {}) if isinstance(original.get("priorities"), dict) else {}
    if priorities:
        story.append(Paragraph("Submitted priorities", styles["APBH2"]))
        pdata=[["Priority","Weight"]]+[[_pdf_text(k),_pdf_text(v)] for k,v in priorities.items()]
        ptable=Table(pdata, repeatRows=1, colWidths=[100*mm,40*mm])
        ptable.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef5")),("GRID",(0,0),(-1,-1),0.2,colors.HexColor("#cfd4da")),("FONTSIZE",(0,0),(-1,-1),7.5)]))
        story.append(ptable)

    structure=original.get("structure_layers", {}) if isinstance(original.get("structure_layers"), dict) else {}
    if structure:
        story.append(Paragraph("Submitted structure targets", styles["APBH2"]))
        sdata=[["Layer","Target"]]+[[_pdf_text(display_text(k)),fmt_pct(v)] for k,v in structure.items()]
        stable=Table(sdata, repeatRows=1, colWidths=[100*mm,40*mm])
        stable.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9eef5")),("GRID",(0,0),(-1,-1),0.2,colors.HexColor("#cfd4da")),("FONTSIZE",(0,0),(-1,-1),7.5)]))
        story.append(stable)

    story += [Spacer(1,5*mm), Paragraph("Important information", styles["APBH2"]), Paragraph(_pdf_text(DISCLAIMER), styles["APBSmall"])]
    doc.build(story)
    return buffer.getvalue()


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
title_col, download_col, logout_col = st.columns([5.2, 1.25, 1])
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

with download_col:
    pdf_bytes = build_portfolio_report_pdf(result)
    if pdf_bytes:
        order_for_file = str(result.get("order_number") or "APB").replace("/", "-").replace("\\", "-")
        st.download_button(
            "Download PDF",
            data=pdf_bytes,
            file_name=f"{order_for_file}_Portfolio_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
            key="download_pdf_top",
        )
    elif not REPORTLAB_AVAILABLE:
        st.caption("PDF export unavailable")

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
            "Structure": display_text(p.get("structure_layer", "–")),
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
                ["Sector", display_text(p.get("sector", "–"))],
                ["Industry", p.get("industry", "–")],
                ["Country / region", p.get("country_region", "–")],
                ["Structure layer", display_text(p.get("structure_layer", "–"))],
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
        "Structure layers are the portfolio's risk/growth architecture: Foundation, Growth, Accelerator and Potential. The chart compares the built allocation with the requested target allocation.",
    )

    st.markdown("### What sits in each layer")
    for layer in ["Fundament", "Vækst", "Accelerator", "Potentiale"]:
        layer_positions = [p for p in positions if normalize(p.get("structure_layer")) == normalize(layer)]
        layer_display = display_text(layer)
        if not layer_positions:
            continue
        with st.expander(f"{layer_display} · {len(layer_positions)} positions", expanded=(layer == "Fundament")):
            rows = [{
                "Name": p.get("name"),
                "Ticker": p.get("ticker"),
                "%PF": fmt_pct(p.get("portfolio_weight_pct")),
                "Base 1Y": fmt_pct(p.get("base_1y_pct")),
                "Sector": display_text(p.get("sector")),
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
            {"Layer": display_text(k), "Target": fmt_pct(v)} for k, v in structure.items()
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

    st.success("You have reached the end of the portfolio presentation. Use Back to revisit any section.")

    final_pdf = build_portfolio_report_pdf(result)
    if final_pdf:
        order_for_file = str(result.get("order_number") or "APB").replace("/", "-").replace("\\", "-")
        st.download_button(
            "Download portfolio report (PDF)",
            data=final_pdf,
            file_name=f"{order_for_file}_Portfolio_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary",
            key="download_pdf_final",
        )


# ------------------------------------------------------------
# PAGE EXPLANATION / COMMON DISCLAIMER / BOTTOM NAVIGATION
# ------------------------------------------------------------
render_page_explanation(step)
st.markdown("---")
st.caption(DISCLAIMER)
st.markdown("<div style='height:.15rem;'></div>", unsafe_allow_html=True)
bottom_left, bottom_middle, bottom_right = st.columns([1, 4, 1])
with bottom_left:
    if step > 0 and st.button("← Back", use_container_width=True, key="nav_back_bottom"):
        st.session_state.wizard_step = step - 1
        st.rerun()
with bottom_right:
    if step < len(STEPS) - 1 and st.button("Next →", type="primary", use_container_width=True, key="nav_next_bottom"):
        st.session_state.wizard_step = step + 1
        st.rerun()
