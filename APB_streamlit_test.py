import io
import json
import os
import re
import requests
import streamlit as st

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

st.set_page_config(
    page_title="Alpha Portfolio Builder",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ------------------------------------------------------------
# VISUAL DESIGN
# ------------------------------------------------------------
st.markdown(
    """
    <style>
    header[data-testid="stHeader"] {display: none !important;}
    div[data-testid="stToolbar"] {display: none !important;}
    div[data-testid="stDecoration"] {display: none !important;}
    div[data-testid="stStatusWidget"] {display: none !important;}
    #MainMenu {visibility: hidden !important;}
    footer {visibility: hidden !important;}

    .block-container {
        padding-top: 0.45rem !important;
        padding-bottom: 1.0rem !important;
        max-width: 1500px !important;
    }

    h1 {
        font-size: 2.0rem !important;
        line-height: 1.1 !important;
        margin-top: 0 !important;
        margin-bottom: 0.15rem !important;
    }
    h2 {
        font-size: 1.35rem !important;
        margin-top: 0.15rem !important;
        margin-bottom: 0.45rem !important;
    }
    h3 {
        font-size: 1.08rem !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.35rem !important;
    }

    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div {
        min-height: 2.0rem !important;
    }
    .stNumberInput input {
        padding-top: 0.22rem !important;
        padding-bottom: 0.22rem !important;
    }
    div[data-testid="stVerticalBlock"] {
        gap: 0.5rem;
    }

    .stButton > button {
        min-height: 2.15rem !important;
        padding-top: 0.25rem !important;
        padding-bottom: 0.25rem !important;
    }

    div[data-testid="stProgress"] {
        margin-top: -0.15rem !important;
        margin-bottom: 0.35rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------
API_URL = "https://simgrova.dk/apb_api/receive.php"

STEPS = [
    "Basic rules",
    "Priorities",
    "Sectors",
    "Industry",
    "Regions",
    "Structure layers",
    "Price target & dividend",
    "Existing portfolio",
    "Review & Build",
]

SECTOR_DEFAULTS = {
    "Technology": 15.0,
    "Financials": 12.0,
    "Healthcare": 12.0,
    "Industrials": 14.0,
    "Consumer Cyclical": 10.0,
    "Consumer Defensive": 10.0,
    "Energy": 8.0,
    "Materials": 7.0,
    "Utilities": 6.0,
    "Transportation": 3.0,
    "Communication": 3.0,
}

REGION_DEFAULTS = {
    "USA": 45.0,
    "Canada": 5.0,
    "Denmark": 5.0,
    "Other Nordics": 5.0,
    "Europe": 20.0,
    "Japan": 5.0,
    "China / Hong Kong": 4.0,
    "Other Asia": 6.0,
    "Emerging Markets": 3.0,
    "Other countries": 2.0,
}

INDUSTRIES = [
    "Aerospace & Defense",
    "Agricultural Commodities/Milling",
    "Air Freight/Couriers",
    "Airlines",
    "Alternative Power Generation",
    "Aluminum",
    "Apparel/Footwear",
    "Auto Parts: OEM",
    "Beverages: Alcoholic",
    "Beverages: Non-Alcoholic",
    "Biotechnology",
    "Building Products",
    "Casinos/Gaming",
    "Chemicals: Agricultural",
    "Chemicals: Specialty",
    "Computer Peripherals",
    "Computer Processing Hardware",
]

ALLOWED_ATTACHMENTS = ["xlsx", "csv", "json", "pdf"]
MAX_FILE_BYTES = 1 * 1024 * 1024

# ------------------------------------------------------------
# SESSION STATE
# ------------------------------------------------------------
def set_default(key, value):
    if key not in st.session_state:
        st.session_state[key] = value

set_default("logged_in", False)
set_default("user_email", "")
set_default("user_name", "")
set_default("wizard_step", 0)
set_default("build_submitted", False)
set_default("submitted_order", None)
set_default("attachment_result", [])
set_default("stored_uploads", [])

set_default("currency", "DKK")
set_default("portfolio_value", 20000)
set_default("minimum_position", 6000)
set_default("minimum_stocks_per_sector", 0)
set_default("maximum_number_of_stocks", 3)

set_default("priority_base_1y", 40)
set_default("priority_stock_score", 30)
set_default("priority_structure_layer", 15)
set_default("priority_sectors", 10)
set_default("priority_industry", 7)
set_default("priority_regions", 5)
set_default("priority_price_target_trend", 10)
set_default("priority_dividend", 0)

for name, value in SECTOR_DEFAULTS.items():
    set_default("sector_" + name, value)
for name in INDUSTRIES:
    set_default("industry_" + name, 0)
for name, value in REGION_DEFAULTS.items():
    set_default("region_" + name, value)

set_default("structure_fundamental", 50.0)
set_default("structure_growth", 30.0)
set_default("structure_accelerator", 15.0)
set_default("structure_potential", 5.0)

set_default("use_target_trend", True)
set_default("use_dividend", False)
set_default("dividend_target", 2.0)

# ------------------------------------------------------------
# WIDGET STATE HELPERS
# ------------------------------------------------------------
def sync_temp(permanent_key):
    st.session_state[permanent_key] = st.session_state["_" + permanent_key]

def prepare_temp(permanent_key):
    temp_key = "_" + permanent_key
    if temp_key not in st.session_state:
        st.session_state[temp_key] = st.session_state[permanent_key]
    return temp_key

def persistent_number(label, key, *, min_value, max_value=None, step=1, fmt=None):
    temp = prepare_temp(key)
    kwargs = {
        "label": label,
        "min_value": min_value,
        "step": step,
        "key": temp,
        "on_change": sync_temp,
        "args": (key,),
    }
    if max_value is not None:
        kwargs["max_value"] = max_value
    if fmt is not None:
        kwargs["format"] = fmt
    return st.number_input(**kwargs)

def persistent_slider(label, key, min_value, max_value):
    temp = prepare_temp(key)
    return st.slider(
        label,
        min_value,
        max_value,
        key=temp,
        on_change=sync_temp,
        args=(key,),
    )

def persistent_checkbox(label, key):
    temp = prepare_temp(key)
    return st.checkbox(
        label,
        key=temp,
        on_change=sync_temp,
        args=(key,),
    )

def persistent_selectbox(label, key, options):
    temp = prepare_temp(key)
    current = st.session_state[key]
    if current not in options:
        st.session_state[key] = options[0]
        st.session_state[temp] = options[0]
    return st.selectbox(
        label,
        options,
        key=temp,
        on_change=sync_temp,
        args=(key,),
    )

# ------------------------------------------------------------
# API HELPERS
# ------------------------------------------------------------
def api_secret():
    return st.secrets["APB_SECRET"]


# ------------------------------------------------------------
# LOGIN
# ------------------------------------------------------------
try:
    ACCESS_CODE = st.secrets["ACCESS_CODE"]
except Exception:
    ACCESS_CODE = "ALPHA2026"

def valid_email(value):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(value or "").strip()))

def show_login():
    st.title("Alpha Portfolio Builder")
    st.subheader("Access")
    st.caption("Enter your email and access code to continue.")

    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        with st.form("login_form"):
            name = st.text_input("Name (optional)")
            email = st.text_input("Email")
            code = st.text_input("Access code", type="password")
            submitted = st.form_submit_button(
                "CONTINUE",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            clean_email = email.strip()
            if not valid_email(clean_email):
                st.error("Please enter a valid email address.")
            elif code != ACCESS_CODE:
                st.error("Incorrect access code.")
            else:
                st.session_state.logged_in = True
                st.session_state.user_name = name.strip()
                st.session_state.user_email = clean_email
                st.rerun()

if not st.session_state.logged_in:
    show_login()
    st.stop()

# ------------------------------------------------------------
# HEADER
# ------------------------------------------------------------
title_col, logout_col = st.columns([6, 1])
with title_col:
    st.title("Alpha Portfolio Builder")
    if st.session_state.user_name:
        st.caption(f"Signed in as: {st.session_state.user_name} · {st.session_state.user_email}")
    else:
        st.caption(f"Signed in as: {st.session_state.user_email}")
with logout_col:
    if st.button("Log out", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_email = ""
        st.session_state.user_name = ""
        st.session_state.wizard_step = 0
        st.rerun()


step = int(st.session_state.wizard_step)
step_name = STEPS[step]

st.markdown(f"**Step {step + 1} of {len(STEPS)} · {step_name}**")
st.progress((step + 1) / len(STEPS))

# ------------------------------------------------------------
# ORDER / REVIEW HELPERS
# ------------------------------------------------------------
def current_order_payload():
    return {
        "type": "apb_order",
        "name": st.session_state.user_name,
        "email": st.session_state.user_email,
        "basic_rules": {
            "currency": st.session_state.currency,
            "portfolio_value": st.session_state.portfolio_value,
            "minimum_position": st.session_state.minimum_position,
            "minimum_stocks_per_sector": st.session_state.minimum_stocks_per_sector,
            "maximum_number_of_stocks": st.session_state.maximum_number_of_stocks,
        },
        "priorities": {
            "Base 1Y": st.session_state.priority_base_1y,
            "Stock score": st.session_state.priority_stock_score,
            "Structure layer": st.session_state.priority_structure_layer,
            "Sectors": st.session_state.priority_sectors,
            "Industry": st.session_state.priority_industry,
            "Regions": st.session_state.priority_regions,
            "Price target trend": st.session_state.priority_price_target_trend,
            "Dividend": st.session_state.priority_dividend,
        },
        "sectors": {
            name: st.session_state["sector_" + name]
            for name in SECTOR_DEFAULTS
        },
        "industry_preferences": {
            name: st.session_state["industry_" + name]
            for name in INDUSTRIES
        },
        "regions": {
            name: st.session_state["region_" + name]
            for name in REGION_DEFAULTS
        },
        "structure_layers": {
            "Fundamental": st.session_state.structure_fundamental,
            "Growth": st.session_state.structure_growth,
            "Accelerator": st.session_state.structure_accelerator,
            "Potential": st.session_state.structure_potential,
        },
        "price_target_trend": {
            "enabled": st.session_state.use_target_trend,
        },
        "dividend": {
            "enabled": st.session_state.use_dividend,
            "portfolio_target_pct": st.session_state.dividend_target,
        },
        "attachments_requested": [
            item["name"] for item in st.session_state.stored_uploads
        ],
    }

def format_money(value, currency):
    return f"{int(round(float(value))):,} {currency}".replace(",", ".")

def show_key_value_rows(rows):
    left, right = st.columns(2)
    split = (len(rows) + 1) // 2
    for i, (label, value) in enumerate(rows):
        target = left if i < split else right
        with target:
            st.write(f"**{label}:** {value}")

def show_full_review(order):
    basic = order["basic_rules"]
    with st.expander("Basic rules", expanded=True):
        rows = []
        if order.get("name"):
            rows.append(("Name", order["name"]))
        rows.extend([
            ("Email", order.get("email", "-")),
            ("Portfolio currency", basic["currency"]),
            ("Total portfolio value", format_money(basic["portfolio_value"], basic["currency"])),
            ("Minimum position size", format_money(basic["minimum_position"], basic["currency"])),
            ("Minimum stocks per sector", int(basic["minimum_stocks_per_sector"])),
            ("Maximum number of stocks", int(basic["maximum_number_of_stocks"])),
        ])
        show_key_value_rows(rows)

    with st.expander("Priorities"):
        show_key_value_rows([
            (name, int(value))
            for name, value in order["priorities"].items()
        ])

    with st.expander("Sectors"):
        show_key_value_rows([
            (name, f"{float(value):.1f}%")
            for name, value in order["sectors"].items()
        ])
        total = sum(float(v) for v in order["sectors"].values())
        st.caption(f"Total: {total:.1f}%")

    with st.expander("Industry preferences"):
        show_key_value_rows([
            (name, f"{int(value):+d}")
            for name, value in order["industry_preferences"].items()
        ])

    with st.expander("Regions"):
        show_key_value_rows([
            (name, f"{float(value):.1f}%")
            for name, value in order["regions"].items()
        ])
        total = sum(float(v) for v in order["regions"].values())
        st.caption(f"Total: {total:.1f}%")

    with st.expander("Structure layers"):
        show_key_value_rows([
            (name, f"{float(value):.1f}%")
            for name, value in order["structure_layers"].items()
        ])
        total = sum(float(v) for v in order["structure_layers"].values())
        st.caption(f"Total: {total:.1f}%")

    with st.expander("Price target & dividend"):
        show_key_value_rows([
            (
                "Price target trend",
                "Enabled" if order["price_target_trend"]["enabled"] else "Disabled",
            ),
            (
                "Dividend optimization",
                "Enabled" if order["dividend"]["enabled"] else "Disabled",
            ),
            (
                "Portfolio dividend target",
                f"{float(order['dividend']['portfolio_target_pct']):.1f}%",
            ),
        ])

    with st.expander("Attachments"):
        attachments = order.get("attachments_requested", [])
        if attachments:
            for name in attachments:
                st.write(f"• {name}")
        else:
            st.write("No attachments.")

# ------------------------------------------------------------
# PDF CONFIRMATION
# ------------------------------------------------------------
def build_confirmation_pdf(order):
    server = order.get("server", {})
    order_number = server.get("order_number", "APB")
    submitted_at = server.get("submitted_at_display", server.get("received_at", "-"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{order_number} - Order Confirmation",
        author="SIMGROVA",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "APBTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_LEFT,
        spaceAfter=5 * mm,
    )
    section_style = ParagraphStyle(
        "APBSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )
    normal_style = ParagraphStyle(
        "APBNormal",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
    )

    story = [
        Paragraph("Alpha Portfolio Builder - Order Confirmation", title_style),
        Paragraph(
            "Please quote your order number if you contact SIMGROVA about this portfolio request.",
            normal_style,
        ),
        Spacer(1, 3 * mm),
    ]

    meta = [
        ["Order number", str(order_number)],
        ["Submitted", str(submitted_at)],
        ["Status", str(server.get("status_display", "Awaiting processing"))],
    ]
    if order.get("name"):
        meta.append(["Name", str(order.get("name"))])
    meta.append(["Email", str(order.get("email", "-"))])
    meta_table = Table(meta, colWidths=[45 * mm, 125 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.lightgrey),
    ]))
    story.append(meta_table)

    def add_section(title, rows):
        story.append(Paragraph(title, section_style))
        data = [[str(k), str(v)] for k, v in rows]
        table = Table(data, colWidths=[75 * mm, 95 * mm], repeatRows=0)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.whitesmoke),
        ]))
        story.append(table)

    basic = order["basic_rules"]
    add_section("Basic rules", [
        ("Portfolio currency", basic["currency"]),
        ("Total portfolio value", format_money(basic["portfolio_value"], basic["currency"])),
        ("Minimum position size", format_money(basic["minimum_position"], basic["currency"])),
        ("Minimum stocks per sector", int(basic["minimum_stocks_per_sector"])),
        ("Maximum number of stocks", int(basic["maximum_number_of_stocks"])),
    ])

    add_section("Priorities", [
        (name, int(value))
        for name, value in order["priorities"].items()
    ])

    add_section("Sectors", [
        (name, f"{float(value):.1f}%")
        for name, value in order["sectors"].items()
    ])

    add_section("Industry preferences", [
        (name, f"{int(value):+d}")
        for name, value in order["industry_preferences"].items()
    ])

    add_section("Regions", [
        (name, f"{float(value):.1f}%")
        for name, value in order["regions"].items()
    ])

    add_section("Structure layers", [
        (name, f"{float(value):.1f}%")
        for name, value in order["structure_layers"].items()
    ])

    add_section("Price target & dividend", [
        (
            "Price target trend",
            "Enabled" if order["price_target_trend"]["enabled"] else "Disabled",
        ),
        (
            "Dividend optimization",
            "Enabled" if order["dividend"]["enabled"] else "Disabled",
        ),
        (
            "Portfolio dividend target",
            f"{float(order['dividend']['portfolio_target_pct']):.1f}%",
        ),
    ])

    attachments = server.get("attachments", [])
    attachment_rows = []
    if attachments:
        for item in attachments:
            status = "Stored" if item.get("saved") else f"Not stored ({item.get('reason', '-')})"
            attachment_rows.append((item.get("original_filename", "Attachment"), status))
    else:
        attachment_rows.append(("Attachments", "None"))

    add_section("Attachments", attachment_rows)

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "The completed portfolio will be returned to the email address shown above.",
        normal_style,
    ))

    doc.build(story)
    return buffer.getvalue()

# ------------------------------------------------------------
# STEP CONTENT
# ------------------------------------------------------------
upload_errors = []

if step == 0:
    st.subheader("Basic rules")
    st.info(
        "Choose the portfolio currency and the basic size limits. "
        "The selected currency is used for both portfolio value and minimum position size."
    )
    left, right = st.columns(2)
    with left:
        persistent_selectbox("Portfolio currency", "currency", ["DKK", "EUR", "USD"])
        persistent_number(
            f"Total portfolio value ({st.session_state['currency']})",
            "portfolio_value",
            min_value=0,
            step=1000,
            fmt="%d",
        )
    with right:
        persistent_number(
            f"Minimum position size ({st.session_state['currency']})",
            "minimum_position",
            min_value=0,
            step=500,
            fmt="%d",
        )
        persistent_number(
            "Minimum stocks per sector",
            "minimum_stocks_per_sector",
            min_value=0,
            step=1,
            fmt="%d",
        )
        persistent_number(
            "Maximum number of stocks",
            "maximum_number_of_stocks",
            min_value=1,
            step=1,
            fmt="%d",
        )

elif step == 1:
    st.subheader("Priorities")
    st.info(
        "These sliders control how strongly each factor influences portfolio construction. "
        "Higher values give that factor more importance relative to the others."
    )
    left, right = st.columns(2)
    with left:
        persistent_slider("Base 1Y", "priority_base_1y", 0, 100)
        persistent_slider("Stock score", "priority_stock_score", 0, 100)
        persistent_slider("Structure layer", "priority_structure_layer", 0, 100)
        persistent_slider("Sectors", "priority_sectors", 0, 100)
    with right:
        persistent_slider("Industry", "priority_industry", 0, 100)
        persistent_slider("Regions", "priority_regions", 0, 100)
        persistent_slider("Price target trend", "priority_price_target_trend", 0, 100)
        persistent_slider("Dividend", "priority_dividend", 0, 100)

elif step == 2:
    st.subheader("Sectors")
    st.info(
        "Set the desired portfolio distribution by sector. "
        "These percentages are optimization targets rather than hard limits."
    )
    names = list(SECTOR_DEFAULTS.keys())
    left, right = st.columns(2)
    for i, name in enumerate(names):
        target = left if i < (len(names) + 1) // 2 else right
        with target:
            persistent_number(
                f"{name} (%)",
                "sector_" + name,
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                fmt="%.1f",
            )
    sector_total = sum(float(st.session_state["sector_" + n]) for n in names)
    st.caption(f"Sector targets total: {sector_total:.1f}%")

elif step == 3:
    st.subheader("Industry preference")
    st.info(
        "Use -100 to strongly avoid an industry, 0 for neutral, and +100 to strongly prioritize it. "
        "This is a preference layer, not a fixed portfolio allocation."
    )
    left, right = st.columns(2)
    split = (len(INDUSTRIES) + 1) // 2
    for i, name in enumerate(INDUSTRIES):
        target = left if i < split else right
        with target:
            persistent_slider(name, "industry_" + name, -100, 100)

elif step == 4:
    st.subheader("Regions")
    st.info(
        "Set the desired geographic distribution of the portfolio. "
        "The percentages are used as optimization targets."
    )
    names = list(REGION_DEFAULTS.keys())
    left, right = st.columns(2)
    for i, name in enumerate(names):
        target = left if i < (len(names) + 1) // 2 else right
        with target:
            persistent_number(
                f"{name} (%)",
                "region_" + name,
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                fmt="%.1f",
            )
    region_total = sum(float(st.session_state["region_" + n]) for n in names)
    st.caption(f"Region targets total: {region_total:.1f}%")

elif step == 5:
    st.subheader("Structure layers")
    st.info(
        "Set the desired mix between Fundamental, Growth, Accelerator and Potential positions. "
        "Fundamental is the most stable layer; Potential is the most speculative."
    )
    left, right = st.columns(2)
    with left:
        persistent_number(
            "Fundamental (%)",
            "structure_fundamental",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            fmt="%.1f",
        )
        persistent_number(
            "Growth (%)",
            "structure_growth",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            fmt="%.1f",
        )
    with right:
        persistent_number(
            "Accelerator (%)",
            "structure_accelerator",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            fmt="%.1f",
        )
        persistent_number(
            "Potential (%)",
            "structure_potential",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            fmt="%.1f",
        )
    structure_total = (
        float(st.session_state.structure_fundamental)
        + float(st.session_state.structure_growth)
        + float(st.session_state.structure_accelerator)
        + float(st.session_state.structure_potential)
    )
    st.caption(f"Structure targets total: {structure_total:.1f}%")

elif step == 6:
    st.subheader("Price target & dividend")
    st.info(
        "These settings add two optional portfolio preferences. "
        "Price target trend uses recent changes in analyst Bear/Base/Bull targets. "
        "Dividend can optimize toward an overall portfolio yield target."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("### Price target trend")
        persistent_checkbox(
            "Use price target trend in optimization",
            "use_target_trend",
        )
        st.caption(
            "Recent changes in analyst target prices are used as a soft preference. "
            "Missing history is treated neutrally."
        )
    with right:
        st.markdown("### Dividend")
        persistent_checkbox(
            "Include dividend in optimization",
            "use_dividend",
        )
        persistent_number(
            "Portfolio dividend target (%)",
            "dividend_target",
            min_value=0.0,
            max_value=20.0,
            step=0.1,
            fmt="%.1f",
        )
        st.caption(
            "The target applies to the overall portfolio yield, not to every individual stock."
        )

elif step == 7:
    st.subheader("Existing portfolio")
    st.info(
        "This step is optional. Attach your current portfolio if you want it considered during processing. "
        "You may attach one .xlsx, one .csv, one .json and one .pdf. Maximum 1 MB per file."
    )
    uploaded = st.file_uploader(
        "Attach existing portfolio files (optional)",
        type=ALLOWED_ATTACHMENTS,
        accept_multiple_files=True,
        key="_portfolio_uploads",
    )

    upload_errors = []
    stored = []

    if uploaded:
        if len(uploaded) > 4:
            upload_errors.append("You can attach a maximum of four files.")

        seen_extensions = set()
        for item in uploaded:
            filename = os.path.basename(item.name)
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            if ext not in ALLOWED_ATTACHMENTS:
                upload_errors.append(f"{filename}: unsupported file type.")
                continue
            if ext in seen_extensions:
                upload_errors.append(f"Only one .{ext} file is allowed per order.")
                continue

            seen_extensions.add(ext)
            data = item.getvalue()

            if len(data) > MAX_FILE_BYTES:
                upload_errors.append(f"{filename}: file is larger than 1 MB.")
                continue

            stored.append({
                "name": filename,
                "type": item.type or "application/octet-stream",
                "data": data,
            })

    st.session_state.stored_uploads = stored

    for message in upload_errors:
        st.error(message)

    if stored:
        st.markdown("### Ready to attach")
        for item in stored:
            st.write(f"✓ {item['name']}")

elif step == 8:
    st.subheader("Review & Build")

    if st.session_state.build_submitted and st.session_state.submitted_order:
        order = st.session_state.submitted_order
        server = order.get("server", {})

        st.success("Your Alpha Portfolio Builder request has been received.")

        pdf_bytes = build_confirmation_pdf(order)
        order_number = server.get("order_number", "APB")
        st.download_button(
            "Download order confirmation (PDF)",
            data=pdf_bytes,
            file_name=f"{order_number}_Order_Confirmation.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )

        st.write(f"**Order number:** {server.get('order_number', '-')}")
        st.write(f"**Submitted:** {server.get('submitted_at_display', server.get('received_at', '-'))}")
        st.write(f"**Status:** {server.get('status_display', 'Awaiting processing')}")
        if order.get("name"):
            st.write(f"**Name:** {order.get('name')}")
        st.write(f"**Email:** {order.get('email', st.session_state.user_email)}")
        st.caption(
            "Please quote your order number if you contact SIMGROVA about this portfolio request."
        )

        st.markdown("### Submitted order")
        show_full_review(order)

        st.stop()

    st.info(
        "Review every submitted value below. Use Back if you want to change anything. "
        "When you press BUILD PORTFOLIO, the order is stored securely at SIMGROVA."
    )

    order = current_order_payload()
    show_full_review(order)

    if st.button("BUILD PORTFOLIO", type="primary", use_container_width=True):
        try:
            multipart_files = [
                (
                    "attachments[]",
                    (item["name"], item["data"], item["type"]),
                )
                for item in st.session_state.stored_uploads
            ]

            response = requests.post(
                API_URL,
                headers={"X-APB-SECRET": api_secret()},
                data={"order_json": json.dumps(order, ensure_ascii=False)},
                files=multipart_files,
                timeout=30,
            )

            result = response.json()

            if response.status_code == 200 and result.get("ok") is True:
                st.session_state.build_submitted = True
                st.session_state.submitted_order = result.get("order")
                st.session_state.attachment_result = result.get("attachments", [])
                st.rerun()
            elif response.status_code == 429:
                st.error("Daily order limit reached. Please try again tomorrow.")
            else:
                st.error(
                    f"The order could not be saved. "
                    f"HTTP {response.status_code}: {response.text}"
                )
        except Exception as exc:
            st.error(f"The order could not be submitted: {exc}")

# ------------------------------------------------------------
# NAVIGATION
# ------------------------------------------------------------
if not st.session_state.build_submitted:
    st.divider()
    back_col, spacer, next_col = st.columns([1, 4, 1])

    with back_col:
        if step > 0:
            if st.button("← Back", use_container_width=True):
                st.session_state.wizard_step -= 1
                st.rerun()

    with next_col:
        if step < len(STEPS) - 1:
            disabled = step == 7 and bool(upload_errors)
            if st.button(
                "Next →",
                type="primary",
                use_container_width=True,
                disabled=disabled,
            ):
                st.session_state.wizard_step += 1
                st.rerun()
