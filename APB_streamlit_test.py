import re
import streamlit as st

st.set_page_config(page_title="Alpha Portfolio Builder", layout="wide")

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
    portfolio_value = st.number_input("Total portfolio value (DKK)", min_value=0, value=20000, step=1000)
    min_position = st.number_input("Minimum position size (DKK)", min_value=0, value=6000, step=500)
    min_sector = st.number_input("Minimum stocks per sector", min_value=0, value=0, step=1)
    max_stocks = st.number_input("Maximum number of stocks", min_value=1, value=3, step=1)

    st.markdown("### Priorities")
    base = st.slider("Base 1Y", 0, 100, 40)
    stock_score = st.slider("Stock score", 0, 100, 30)
    structure = st.slider("Structure layer", 0, 100, 15)
    sectors_weight = st.slider("Sectors", 0, 100, 10)
    industry_weight = st.slider("Industry", 0, 100, 7)
    regions_weight = st.slider("Regions", 0, 100, 5)
    target_trend = st.slider("Price target trend", 0, 100, 10)
    dividend_weight = st.slider("Dividend", 0, 100, 0)

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
            name + " (%)", 0.0, 100.0, value, 1.0, key="sector_" + name
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
            name + " (%)", 0.0, 100.0, value, 1.0, key="region_" + name
        )

    st.markdown("### Price target trend")
    use_trend = st.checkbox("Use price target trend in optimization", value=True)

    st.markdown("### Dividend")
    use_dividend = st.checkbox("Include dividend in optimization")
    dividend_target = st.number_input(
        "Portfolio dividend target (%)", 0.0, 20.0, 2.0, 0.1
    )

with c4:
    st.markdown("### Structure layers")
    fundamental = st.number_input("Fundamental (%)", 0.0, 100.0, 50.0, 1.0)
    growth = st.number_input("Growth (%)", 0.0, 100.0, 30.0, 1.0)
    accelerator = st.number_input("Accelerator (%)", 0.0, 100.0, 15.0, 1.0)
    potential = st.number_input("Potential (%)", 0.0, 100.0, 5.0, 1.0)

st.divider()

if "build_submitted" not in st.session_state:
    st.session_state.build_submitted = False
if "uploaded_filename" not in st.session_state:
    st.session_state.uploaded_filename = ""

if not st.session_state.build_submitted:
    st.markdown("### Optional existing portfolio")
    uploaded_portfolio = st.file_uploader(
        "Upload existing portfolio (optional)",
        type=["csv", "xlsx", "xls", "json", "txt"],
        help="Attach your current portfolio if you want it considered together with your Phase 1 preferences."
    )

    st.info(
        "When you press BUILD PORTFOLIO, your Phase 1 settings and any attached portfolio file "
        "will be prepared for submission. The finished portfolio will later be returned to the "
        "email address you used to sign in. No email is sent in this test version."
    )

    if st.button("BUILD PORTFOLIO", type="primary", use_container_width=True):
        st.session_state.build_submitted = True
        st.session_state.uploaded_filename = uploaded_portfolio.name if uploaded_portfolio else ""
        st.rerun()

else:
    st.success("Your portfolio request is ready for submission.")

    st.markdown("### What happens next")
    st.write(
        "Your Phase 1 settings have been collected. In the final version, they will be sent "
        "for processing together with your optional portfolio attachment."
    )
    st.write(f"The finished portfolio will be returned to: **{st.session_state.user_email}**")

    if st.session_state.uploaded_filename:
        st.write(f"Attached existing portfolio: **{st.session_state.uploaded_filename}**")
    else:
        st.write("No existing portfolio was attached.")

    st.warning("Test version: nothing has been emailed or submitted yet.")

    if st.button("Back to portfolio settings", use_container_width=True):
        st.session_state.build_submitted = False
        st.session_state.uploaded_filename = ""
        st.rerun()
