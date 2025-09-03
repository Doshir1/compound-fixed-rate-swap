import streamlit as st
import requests
import pandas as pd

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Simulator")
st.write("Deposit ETH as collateral, borrow USDC, and compare Fixed vs Floating swaps.")

# --------------------------
# 2. Fetch historical APR data (The Graph)
# --------------------------
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"

headers = {"Content-Type": "application/json"}

query = """
{
  dailyMarketAccountings(first: 200, where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" }) {
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

df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")

# --------------------------
# 3. Get ETH collateral factors from Compound API
# --------------------------
comet_api = "https://api.compound.finance/v2/ctoken"  # Compound v2 API (still valid for factors)

eth_ctoken = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"  # WETH address
collateral_data = requests.get(comet_api).json()

borrow_cf = None
liquidate_cf = None
for token in collateral_data["cToken"]:
    if token["underlying_address"].lower() == eth_ctoken.lower():
        borrow_cf = float(token["collateral_factor"]["value"])  # e.g. 0.75
        liquidate_cf = float(token["reserve_factor"]["value"])  # fallback
        break

if borrow_cf is None:
    borrow_cf = 0.75  # fallback assumption

st.subheader("📊 Collateral Factors")
st.write(f"**ETH Borrow Collateral Factor**: {borrow_cf:.2f}")

# --------------------------
# 4. Decide Fixed Rate (from backtest)
# --------------------------
avg_borrow_rate = df["borrowApr"].mean()
fixed_rate = avg_borrow_rate * 1.1  # set 10% above average floating
st.write(f"**Proposed Fixed Rate**: {fixed_rate*100:.2f}%")

# --------------------------
# 5. Swap Simulation
# --------------------------
st.subheader("💡 Swap Simulation")

eth_price = 2000  # USD (for simplicity, normally pull from oracle)
eth_collateral = st.number_input("ETH Collateral Supplied", min_value=1.0, value=10.0, step=0.5)

borrow_capacity = eth_collateral * eth_price * borrow_cf
st.write(f"Borrow Capacity (in USDC): **${borrow_capacity:,.2f}**")

periods = st.slider("Number of Periods", 1, 12, 6)

# Example fixed vs floating
fixed_payment = borrow_capacity * fixed_rate
floating_rates = df["borrowApr"].tail(periods).values

results = []
for i in range(periods):
    floating_payment = borrow_capacity * floating_rates[i]
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
