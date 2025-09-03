import streamlit as st
import requests
import pandas as pd

# --------------
# Page setup
# --------------
st.title("Compound Fixed Rate Swap Simulator (Automated ETH Price)")
st.write("ETH USD price is fetched automatically — no user input needed.")

# --------------
# Collateral Factors (hardcoded)
# --------------
BORROW_CF = 0.825
LIQ_CF = 0.88
LIQ_PENALTY = 0.07

st.sidebar.header("Collateral Parameters")
st.sidebar.write(f"Borrow CF: {BORROW_CF*100:.2f}%")
st.sidebar.write(f"Liquidate CF: {LIQ_CF*100:.2f}%")
st.sidebar.write(f"Liquidation Penalty: {LIQ_PENALTY*100:.2f}%")

# --------------
# The Graph endpoint + GraphQL queries
# --------------
API_KEY = "3b6cc500833cb7c07f3eb2e97bc88709"
GRAPH_URL = f"https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"
HEADERS = {"Content-Type": "application/json"}

apr_query = """
{
  dailyMarketAccountings(first: 200, where: { market: "0xc3d688b66703497daa19211eedff47f25384cdc3" }) {
    timestamp
    accounting {
      borrowApr
      supplyApr
    }
  }
}
"""
apr_resp = requests.post(GRAPH_URL, json={"query": apr_query}, headers=HEADERS).json()
df = pd.DataFrame({
    "timestamp": [x["timestamp"] for x in apr_resp["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(x["accounting"]["borrowApr"]) for x in apr_resp["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(x["accounting"]["supplyApr"]) for x in apr_resp["data"]["dailyMarketAccountings"]]
})
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")

price_query = """
{
  bundle(id: "1") {
    ethPrice
  }
}
"""
price = requests.post(GRAPH_URL, json={"query": price_query}, headers=HEADERS).json()
eth_price = float(price["data"]["bundle"]["ethPrice"])
st.write(f"**Current ETH Price (USD):** ${eth_price:,.2f}")

# --------------
# Display APR data
# --------------
st.subheader("Historical APRs")
st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])
st.dataframe(df.tail(5))

# --------------
# Swap simulator
# --------------
st.subheader("Fixed vs Floating Swap")

eth_collateral = st.number_input("ETH Collateral", min_value=0.1, value=10.0, step=0.1)
fixed_rate = st.number_input("Fixed Rate (%)", min_value=0.0, value=5.0, step=0.1)
periods = st.slider("Number of Periods", min_value=1, max_value=12, value=6)

borrow_usd = eth_collateral * eth_price * BORROW_CF
st.write(f"Max borrowable: **${borrow_usd:,.2f}**")

fixed_payment = borrow_usd * (fixed_rate / 100)
floating_rates = df["borrowApr"].tail(periods).values

results = []
for i in range(periods):
    float_pay = borrow_usd * floating_rates[i]
    net = fixed_payment - float_pay
    results.append({
        "Period": i + 1,
        "Floating Rate": f"{floating_rates[i]*100:.2f}%",
        "Float Payment (USD)": f"${float_pay:,.2f}",
        "Fixed Payment (USD)": f"${fixed_payment:,.2f}",
        "Net Cashflow (USD)": f"${net:,.2f}"
    })

res_df = pd.DataFrame(results)
st.dataframe(res_df.set_index("Period"))
st.line_chart(res_df.set_index("Period")[["Floating Payment (USD)", "Fixed Payment (USD)"]])
