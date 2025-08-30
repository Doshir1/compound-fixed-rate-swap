import streamlit as st
import requests
import pandas as pd

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound APR Viewer & Fixed Rate Swap Idea")
st.write("This tool shows historical Supply & Borrow APRs from Compound, and explains how swaps could work.")

# --------------------------
# 2. Fetch data from The Graph
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
# 3. Show data
# --------------------------
st.subheader("📊 Historical APR Data")
st.write("Borrow and Supply APRs over time:")

st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])

st.write("Raw data preview:")
st.dataframe(df.tail(10))

# --------------------------
# 4. Fixed Swap Simulator (conceptual)
# --------------------------
st.subheader("💡 Fixed Rate Swap Simulator (Concept)")

notional = st.number_input("Notional Amount (in ETH)", min_value=1, value=100)
fixed_rate = st.number_input("Fixed Rate (as %)", min_value=0.0, value=5.0, step=0.1)
periods = st.slider("Number of Periods", 1, 12, 6)

# Example: simple fixed vs floating cashflow calculation
floating_rates = df["borrowApr"].tail(periods).values
fixed_payment = notional * (fixed_rate / 100)

st.write(f"Fixed Payment per period: **{fixed_payment:.2f} ETH**")

results = []
for i in range(periods):
    floating_payment = notional * (floating_rates[i])
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
