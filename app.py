import streamlit as st
import requests
import pandas as pd

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound v3 Swap Tool")
st.write("This app shows Compound APR data, collateral factors, and simulates a fixed-vs-floating interest rate swap.")

# --------------------------
# 2. The Graph API setup
# --------------------------
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"

headers = {"Content-Type": "application/json"}

# --------------------------
# 3. Query APR data
# --------------------------
apr_query = """
{
  dailyMarketAccountings(first: 100, where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" }) {
    timestamp
    accounting {
      borrowApr
      supplyApr
    }
  }
}
"""

apr_response = requests.post(url, json={"query": apr_query}, headers=headers).json()

# Convert APR data into DataFrame
df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in apr_response["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(entry["accounting"]["borrowApr"]) for entry in apr_response["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(entry["accounting"]["supplyApr"]) for entry in apr_response["data"]["dailyMarketAccountings"]]
})
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")

# --------------------------
# 4. Query Collateral Factors
# --------------------------
collateral_query = """
{
  markets(where: { id: "0xc3d688b66703497daa19211eedff47f25384cdc3" }) {
    name
    collateralAssets {
      id
      borrowCollateralFactor
      liquidateCollateralFactor
      liquidationFactor
    }
  }
}
"""

collateral_response = requests.post(url, json={"query": collateral_query}, headers=headers).json()
collateral_data = collateral_response["data"]["markets"][0]["collateralAssets"]

collateral_df = pd.DataFrame(collateral_data)
collateral_df["borrowCollateralFactor"] = collateral_df["borrowCollateralFactor"].astype(float) / 1e18
collateral_df["liquidateCollateralFactor"] = collateral_df["liquidateCollateralFactor"].astype(float) / 1e18
collateral_df["liquidationFactor"] = collateral_df["liquidationFactor"].astype(float) / 1e18

# --------------------------
# 5. Show Data
# --------------------------
st.subheader("📊 Historical APR Data")
st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])
st.write("Raw data preview:")
st.dataframe(df.tail(10))

st.subheader("📌 Collateral Factors")
st.dataframe(collateral_df)

# --------------------------
# 6. Swap Simulator
# --------------------------
st.subheader("💡 Fixed vs Floating Swap Simulator")

notional = st.number_input("Collateral (ETH)", min_value=1.0, value=10.0)
eth_price = 3000  # you could pull this live via API
borrow_factor = collateral_df.iloc[0]["borrowCollateralFactor"]  # take first asset for now

# Borrowable USD
borrowable_usd = notional * eth_price * borrow_factor
st.write(f"With {notional} ETH, you can borrow up to **${borrowable_usd:,.2f}**")

# Choose fixed rate
fixed_rate = st.slider("Choose Fixed Rate (%)", 1.0, 10.0, 5.0)
periods = st.slider("Number of Periods", 1, 12, 6)

# Simulate payments
floating_rates = df["borrowApr"].tail(periods).values
fixed_payment = borrowable_usd * (fixed_rate / 100)

results = []
for i in range(periods):
    floating_payment = borrowable_usd * floating_rates[i]
    net_cashflow = fixed_payment - floating_payment
    results.append({
        "Period": i + 1,
        "Floating Rate": floating_rates[i],
        "Floating Payment": floating_payment,
        "Fixed Payment": fixed_payment,
        "Net Cashflow": net_cashflow
    })

results_df = pd.DataFrame(results)
st.dataframe(results_df)
st.line_chart(results_df[["Floating Payment", "Fixed Payment"]].set_index(results_df["Period"]))
