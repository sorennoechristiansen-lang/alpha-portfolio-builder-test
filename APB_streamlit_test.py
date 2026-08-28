import re
import json
import os
import requests
import streamlit as st

st.set_page_config(page_title="Alpha Portfolio Builder", layout="wide")

st.markdown("""
<style>
/* More compact page typography */
h1 { font-size: 2.15rem !important; margin-bottom: 0.35rem !important; }
h2 { font-size: 1.45rem !important; margin-top: 0.5rem !important; margin-bottom: 0.55rem !important; }
h3 { font-size: 1.12rem !important; margin-top: 0.35rem !important; margin-bottom: 0.45rem !important; }

/* Compact input widgets */
div[data-baseweb="input"] > div {
    min-height: 2.25rem !important;
}
div[data-baseweb="select"] > div {
    min-height: 2.25rem !important;
}
.stNumberInput input {
    padding-top: 0.30rem !important;
    padding-bottom: 0.30rem !important;
}

/* Slightly tighter vertical spacing */
div[data-testid="stVerticalBlock"] {
    gap: 0.65rem;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# SIMPLE ACCESS PAGE
# ------------------------------------------------------------
# Local fallback code for testing.
# Later on Streamlit Cloud we can place ACCESS_CODE in Secrets,
# so the real code does not need to be stored in GitHub.
try:
    ACCESS_CODE = st.secrets["ACCESS_CODE"]
except Exception:
    ACCESS_CODE = "ALPHA2026"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_email" not in st.session_state:
    st.session_state.user_email = ""

def valid_email(value):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(value or "").strip()))

def login_page():
    st.title("Alpha Portfolio Builder")
    st.subheader("Access")

    with st.form("login_form"):
        email = st.text_input("Email")
        code = st.text_input("Access code", type="password")
        submitted = st.form_submit_button("CONTINUE", type="primary", use_container_width=True)

    if submitted:
        if not valid_email(email):
            st.error("Please enter a valid email address.")
        elif code != ACCESS_CODE:
            st.error("Incorrect access code.")
        else:
            st.session_state.logged_in = True
            st.session_state.user_email = email.strip()
            st.rerun()

if not st.session_state.logged_in:
    login_page()
    st.stop()

# ------------------------------------------------------------
# ALPHA PORTFOLIO BUILDER – PHASE 1
# ------------------------------------------------------------
top_left, top_right = st.columns([5, 1])
with top_left:
    st.title("Alpha Portfolio Builder")
    st.subheader("Phase 1 – Build portfolio")
    st.caption("Set your portfolio preferences.")
with top_right:
    st.write("")
    st.write("")
    if st.button("Log out", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user_email = ""
        st.rerun()

st.caption(f"Signed in as: {st.session_state.user_email}")


c1, c2, c3, c4 = st.columns([1.0, 1.15, 0.8, 0.8])

with c1:
    st.markdown("### Basic rules")
    currency = st.selectbox("Portfolio currency", ["DKK", "EUR", "USD"], index=0)
    portfolio_value = st.number_input(
        f"Total portfolio value ({currency})",
        min_value=0.0, value=20000.0, step=1000.0, format="%.1f"
    )
    min_position = st.number_input(
        f"Minimum position size ({currency})",
        min_value=0.0, value=6000.0, step=500.0, format="%.1f"
    )
    min_sector = st.number_input("Minimum stocks per sector", min_value=0, value=0, step=1)
    max_stocks = st.number_input("Maximum number of stocks", min_value=1, value=3, step=1)

    with st.expander("Help – Basic rules"):
        st.write(
            "Choose the portfolio currency and the main size limits. "
            "The same currency is used for total portfolio value and minimum position size."
        )

    st.markdown("### Priorities")
    base = st.slider("Base 1Y", 0, 100, 40)
    stock_score = st.slider("Stock score", 0, 100, 30)
    structure = st.slider("Structure layer", 0, 100, 15)
    sectors_weight = st.slider("Sectors", 0, 100, 10)
    industry_weight = st.slider("Industry", 0, 100, 7)
    regions_weight = st.slider("Regions", 0, 100, 5)
    target_trend = st.slider("Price target trend", 0, 100, 10)
    dividend_weight = st.slider("Dividend", 0, 100, 0)

    with st.expander("Help – Priorities"):
        st.write(
            "The sliders control how strongly each factor influences the portfolio construction. "
            "Higher values give that factor more importance relative to the others."
        )

with c2:
    st.markdown("### Sectors")
    sector_defaults = {
        "Technology": 15.0, "Financials": 12.0, "Healthcare": 12.0,
        "Industrials": 14.0, "Consumer Cyclical": 10.0,
        "Consumer Defensive": 10.0, "Energy": 8.0, "Materials": 7.0,
        "Utilities": 6.0, "Transportation": 3.0, "Communication": 3.0
    }
    sectors = {}
    for name, value in sector_defaults.items():
        sectors[name] = st.number_input(
            name + " (%)", 0.0, 100.0, value, 0.1, format="%.1f", key="sector_" + name
        )

    with st.expander("Help – Sectors"):
        st.write(
            "Set the desired sector distribution. These are portfolio targets, not hard limits."
        )

    st.markdown("### Industry preference")
    st.caption("-100 = strong avoidance · 0 = neutral · +100 = strong priority")
    industries = [
        "Aerospace & Defense", "Agricultural Commodities/Milling",
        "Air Freight/Couriers", "Airlines", "Alternative Power Generation",
        "Aluminum", "Apparel/Footwear", "Auto Parts: OEM",
        "Beverages: Alcoholic", "Beverages: Non-Alcoholic",
        "Biotechnology", "Building Products", "Casinos/Gaming",
        "Chemicals: Agricultural", "Chemicals: Specialty",
        "Computer Peripherals", "Computer Processing Hardware"
    ]
    industry = {
        name: st.slider(name, -100, 100, 0, key="industry_" + name)
        for name in industries
    }

    with st.expander("Help – Industry preference"):
        st.write(
            "Use -100 to strongly avoid an industry, 0 for neutral, and +100 to strongly prioritize it."
        )

with c3:
    st.markdown("### Regions")
    region_defaults = {
        "USA": 45.0, "Canada": 5.0, "Denmark": 5.0, "Other Nordics": 5.0,
        "Europe": 20.0, "Japan": 5.0, "China / Hong Kong": 4.0,
        "Other Asia": 6.0, "Emerging Markets": 3.0, "Other countries": 2.0
    }
    regions = {}
    for name, value in region_defaults.items():
        regions[name] = st.number_input(
            name + " (%)", 0.0, 100.0, value, 0.1, format="%.1f", key="region_" + name
        )

    with st.expander("Help – Regions"):
        st.write(
            "Set the desired geographic distribution of the portfolio. The targets are used in optimization."
        )

    st.markdown("### Price target trend")
    use_trend = st.checkbox("Use price target trend in optimization", value=True)
    with st.expander("Help – Price target trend"):
        st.write(
            "When enabled, recent changes in analyst Bear/Base/Bull targets are included as a soft preference."
        )

    st.markdown("### Dividend")
    use_dividend = st.checkbox("Include dividend in optimization")
    dividend_target = st.number_input(
        "Portfolio dividend target (%)", 0.0, 20.0, 2.0, 0.1, format="%.1f"
    )
    with st.expander("Help – Dividend"):
        st.write(
            "Enable this if the portfolio should also be optimized toward an overall dividend yield target."
        )

with c4:
    st.markdown("### Structure layers")
    fundamental = st.number_input("Fundamental (%)", 0.0, 100.0, 50.0, 0.1, format="%.1f")
    growth = st.number_input("Growth (%)", 0.0, 100.0, 30.0, 0.1, format="%.1f")
    accelerator = st.number_input("Accelerator (%)", 0.0, 100.0, 15.0, 0.1, format="%.1f")
    potential = st.number_input("Potential (%)", 0.0, 100.0, 5.0, 0.1, format="%.1f")

    with st.expander("Help – Structure layers"):
        st.write(
            "Set the desired mix between Fundamental, Growth, Accelerator and Potential positions."
        )

st.divider()

ALLOWED_ATTACHMENTS = ["xlsx", "csv", "json", "pdf"]
MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB

if "build_submitted" not in st.session_state:
    st.session_state.build_submitted = False
if "order_filename" not in st.session_state:
    st.session_state.order_filename = ""
if "attachment_result" not in st.session_state:
    st.session_state.attachment_result = []

st.markdown("### Optional existing portfolio")
st.caption(
    "You may attach up to four files: one .xlsx, one .csv, one .json and one .pdf. "
    "Maximum 1 MB per file."
)
with st.expander("Help – Existing portfolio"):
    st.write(
        "This is optional. Attach your current portfolio if you want it considered during processing. "
        "Only one file of each accepted type can be attached."
    )

uploaded_files = st.file_uploader(
    "Attach existing portfolio files (optional)",
    type=ALLOWED_ATTACHMENTS,
    accept_multiple_files=True,
)

upload_errors = []
validated_files = []

if uploaded_files:
    if len(uploaded_files) > 4:
        upload_errors.append("You can attach a maximum of four files.")

    seen_extensions = set()
    for uploaded in uploaded_files:
        filename = os.path.basename(uploaded.name)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext not in ALLOWED_ATTACHMENTS:
            upload_errors.append(f"{filename}: unsupported file type.")
            continue

        if ext in seen_extensions:
            upload_errors.append(
                f"Only one .{ext} file is allowed per order."
            )
            continue

        seen_extensions.add(ext)

        size = len(uploaded.getvalue())
        if size > MAX_FILE_BYTES:
            upload_errors.append(
                f"{filename}: file is larger than 1 MB."
            )
            continue

        validated_files.append(uploaded)

if upload_errors:
    for message in upload_errors:
        st.error(message)

st.info(
    "When you press BUILD PORTFOLIO, your Phase 1 settings and accepted attachments "
    "will be sent securely to SIMGROVA for processing. "
    "If the daily upload limit has been reached, the order may still be stored without attachments. "
    "The finished portfolio will later be returned to the email address you used to sign in."
)

if not st.session_state.build_submitted:
    if st.button(
        "BUILD PORTFOLIO",
        type="primary",
        use_container_width=True,
        disabled=bool(upload_errors),
    ):
        try:
            secret = st.secrets["APB_SECRET"]

            payload = {
                "type": "apb_order",
                "email": st.session_state.user_email,
                "basic_rules": {
                    "currency": currency,
                    "portfolio_value": portfolio_value,
                    "minimum_position": min_position,
                    "minimum_stocks_per_sector": min_sector,
                    "maximum_number_of_stocks": max_stocks,
                },
                "priorities": {
                    "base_1y": base,
                    "stock_score": stock_score,
                    "structure_layer": structure,
                    "sectors": sectors_weight,
                    "industry": industry_weight,
                    "regions": regions_weight,
                    "price_target_trend": target_trend,
                    "dividend": dividend_weight,
                },
                "sectors": sectors,
                "industry_preferences": industry,
                "regions": regions,
                "structure_layers": {
                    "Fundamental": fundamental,
                    "Growth": growth,
                    "Accelerator": accelerator,
                    "Potential": potential,
                },
                "price_target_trend": {
                    "enabled": use_trend,
                },
                "dividend": {
                    "enabled": use_dividend,
                    "portfolio_target_pct": dividend_target,
                },
                "attachments_requested": [os.path.basename(f.name) for f in validated_files],
            }

            multipart_files = []
            for f in validated_files:
                multipart_files.append(
                    (
                        "attachments[]",
                        (
                            os.path.basename(f.name),
                            f.getvalue(),
                            f.type or "application/octet-stream",
                        ),
                    )
                )

            response = requests.post(
                "https://simgrova.dk/apb_api/receive.php",
                headers={"X-APB-SECRET": secret},
                data={"order_json": json.dumps(payload, ensure_ascii=False)},
                files=multipart_files,
                timeout=30,
            )

            result = response.json()

            if response.status_code == 200 and result.get("ok") is True:
                st.session_state.build_submitted = True
                st.session_state.order_filename = result.get("filename", "")
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

else:
    st.success("Your Alpha Portfolio Builder request has been received.")

    st.markdown("### What happens next")
    st.write(
        "Your Phase 1 settings have been stored securely at SIMGROVA and are ready for processing."
    )
    st.write(
        f"The finished portfolio will be returned to: **{st.session_state.user_email}**"
    )

    if st.session_state.order_filename:
        st.caption(f"Order reference: {st.session_state.order_filename}")

    results = st.session_state.get("attachment_result", [])
    if results:
        st.markdown("### Attachments")
        for item in results:
            original = item.get("original_filename", "Attachment")
            if item.get("saved"):
                st.write(f"✅ {original} – stored")
            else:
                reason = item.get("reason", "not stored")
                if reason == "daily_upload_limit_reached":
                    st.write(f"⚠️ {original} – not stored because the daily upload limit was reached")
                else:
                    st.write(f"⚠️ {original} – not stored ({reason})")

    if st.button("Back to portfolio settings", use_container_width=True):
        st.session_state.build_submitted = False
        st.session_state.order_filename = ""
        st.session_state.attachment_result = []
        st.rerun()
