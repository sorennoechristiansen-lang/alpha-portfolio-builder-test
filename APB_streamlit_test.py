import streamlit as st

st.set_page_config(
    page_title="Alpha Portfolio Builder - Test",
    page_icon="📈",
    layout="centered"
)

st.title("Alpha Portfolio Builder")
st.subheader("Test web app")

st.write(
    "This is a simple test version to verify that a Python program "
    "can run as a web app."
)

startbeloeb = st.number_input(
    "Investment amount (DKK)",
    min_value=0.0,
    value=100000.0,
    step=1000.0
)

afkast = st.number_input(
    "Expected annual return (%)",
    value=8.0,
    step=0.5
)

aar = st.number_input(
    "Number of years",
    min_value=0,
    value=10,
    step=1
)

if st.button("Calculate"):
    slutvaerdi = startbeloeb * (1 + afkast / 100) ** aar
    gevinst = slutvaerdi - startbeloeb

    st.success(f"Final value: {slutvaerdi:,.2f} DKK")
    st.write(f"Total gain: {gevinst:,.2f} DKK")
