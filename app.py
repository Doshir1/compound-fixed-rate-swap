import streamlit as st
import requests
import pandas as pd

# --------------------------
# 1. Page setup
# --------------------------
st.title("📈 Compound Fixed Rate Swap Simulator")
st.write("This app shows historical APRs and simulates a simple fixed vs floating rate swap using ETH as collateral.")

# --------------------------
# 2. Collateral Factors (hardcoded)
# --------------------------
BORROW_COLLATERAL_FACTOR = 0.825   # 82.5%
LIQUIDATE_COLLATERAL_FACTOR = 0.88 # 88.0%
LIQUIDATION_PENALTY = 0.07         # 7.0%

st.sidebar.subheader("⚖️ Collateral Parameters")
st.sidebar.write(f"Borrow Collateral Factor: {BORROW_COLLATERAL_FACTOR*100:.2f}%")
st.sidebar.write(f"Liquidate Collateral Factor: {LIQUIDATE_COLLATERAL_FACTOR*100:.2f}%")
st.sidebar.write(f"Liquidation Penalty: {LIQUIDATION_PENALTY*100:.2f}%")

# --------------------------
# 3. Fetch APR data from The Graph
# --------------------------
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"

headers = {"Content-Type": "application/json"}

query = """
{
  dailyMarketAccountings(first: 100, where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" }) {
    timestamp
    accounting {
      borrowApr
      supplyApr
      price
    }
  }
}
"""

response = requests.post(url, json={"query": query}, headers=headers)
data = response.json()

# Convert to DataFrame
df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in data["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(entry["accounting"]["borrowApr"]) for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(entry["accounting"]["supplyApr"]) for entry in data["data"]["dailyMarketAccountings"]]
})

# Convert timestamp to readable date
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")

# --------------------------
# 4. Show data
# --------------------------
st.subheader("📊 Historical APR Data")
st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])

st.write("Raw data preview:")
st.dataframe(df.tail(10))

# --------------------------
# 5. Fixed Rate Swap Simulator
# --------------------------
st.subheader("💡 Fixed Rate Swap Simulator")

# User inputs
eth_price = (price)
eth_deposit = st.number_input("ETH Deposited as Collateral", min_value=0.1, value=10.0)
fixed_rate = st.number_input("Fixed Rate (as %)", min_value=0.0, value=5.0, step=0.1)
periods = st.slider("Number of Periods", 1, 12, 6)

# Max borrow based on collateral factor
max_borrow_usd = eth_deposit * eth_price * BORROW_COLLATERAL_FACTOR
st.write(f"💰 With {eth_deposit} ETH, you can safely borrow up to **${max_borrow_usd:,.2f}**")

# Swap calculation
notional = max_borrow_usd / eth_price  # borrow notional in ETH terms
floating_rates = df["borrowApr"].tail(periods).values
fixed_payment = notional * (fixed_rate / 100)

results = []
for i in range(periods):
    floating_payment = notional * (floating_rates[i])
    net_cashflow = fixed_payment - floating_payment
    results.append({
        "Period": i + 1,
        "Floating Rate": floating_rates[i],
        "Floating Payment (ETH)": floating_payment,
        "Fixed Payment (ETH)": fixed_payment,
        "Net Cashflow (ETH)": net_cashflow
    })

results_df = pd.DataFrame(results)

st.dataframe(results_df)
st.line_chart(results_df[["Floating Payment (ETH)", "Fixed Payment (ETH)"]].set_index(results_df["Period"]))
