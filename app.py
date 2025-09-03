import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Prototype")
st.write("This app shows Compound APR data, fetches ETH price from Polygon.io, "
         "and simulates a simple fixed–floating swap using ETH as collateral.")

# --------------------------
# 2. Collateral Factors
# --------------------------
BORROW_CF = 0.825
LIQUIDATE_CF = 0.88
LIQ_PENALTY = 0.07

# --------------------------
# 3. Fetch ETH Price
# --------------------------
API_KEY_POLYGON = "on0FmvftNux2r3sVEmDVr4mR6n9e0ZCc"

@st.cache_data(ttl=300)
def get_eth_price_usd():
    url = f"https://api.polygon.io/v2/aggs/ticker/X:ETHUSD/prev?apiKey={API_KEY_POLYGON}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    return float(data["results"][0]["c"])

eth_price = None
try:
    eth_price = get_eth_price_usd()
    st.success(f"💰 Current ETH Price (USD): ${eth_price:,.2f}")
except Exception as e:
    st.error("Failed to fetch ETH price from Polygon.io.")
    eth_price = st.number_input("Enter ETH Price manually (USD)", min_value=500.0, value=2000.0, step=10.0)

# --------------------------
# 4. Fetch APR Data from The Graph
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

df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in data["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(entry["accounting"]["borrowApr"]) for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(entry["accounting"]["supplyApr"]) for entry in data["data"]["dailyMarketAccountings"]]
})

df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")

# --------------------------
# 4b. Convert borrow APR to per-second rate
# --------------------------
SECONDS_PER_YEAR = 365 * 24 * 60 * 60
df["borrow_rate_per_second"] = (1 + df["borrowApr"]) ** (1 / SECONDS_PER_YEAR) - 1

# --------------------------
# 5. Show Historical APRs
# --------------------------
st.subheader("📊 Historical APR Data")
st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])
st.dataframe(df.tail(10))

# --------------------------
# 6. Swap Simulator
# --------------------------
st.subheader("💡 Fixed Rate Swap Simulator")

eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
fixed_rate_input = st.number_input("Fixed Rate (annual %)", min_value=0.0, value=5.0, step=0.1)
periods = st.slider("Number of Periods (months)", 1, 12, 6)

collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF

st.write(f"🔒 Collateral Value: ${collateral_value_usd:,.2f}")
st.write(f"📉 Max Borrow Capacity (using {BORROW_CF*100:.1f}% factor): ${max_borrow_usd:,.2f}")

# --------------------------
# 7. Backtest for Suggested Fixed Rate
# --------------------------
st.subheader("💡 Suggested Fixed Rate (Backtest)")

floating_aprs_per_sec = df["borrow_rate_per_second"].tail(periods).values

def suggest_fixed_rate(floating_rates_per_sec, margin=1e-6):
    """
    Suggest the lowest fixed rate slightly above historical floating rates.
    """
    max_floating = max(floating_rates_per_sec)
    return max_floating + margin

suggested_fixed_rate_per_sec = suggest_fixed_rate(floating_aprs_per_sec)
suggested_fixed_rate_annual = (1 + suggested_fixed_rate_per_sec) ** SECONDS_PER_YEAR - 1

st.write(f"📈 Suggested Fixed Rate (annual %): {suggested_fixed_rate_annual*100:.2f}%")

# --------------------------
# 8. Cashflow Simulation
# --------------------------
fixed_payment = max_borrow_usd * (suggested_fixed_rate_annual) / 12

results = []
for i in range(periods):
    floating_payment = max_borrow_usd * df["borrowApr"].tail(periods).values[i] / 12
    net_cashflow = fixed_payment - floating_payment
    results.append({
        "Period": i + 1,
        "Floating Rate": f"{df['borrowApr'].tail(periods).values[i]*100:.2f}%",
        "Floating Payment": floating_payment,
        "Fixed Payment": fixed_payment,
        "Net Cashflow": net_cashflow
    })

results_df = pd.DataFrame(results)
st.dataframe(results_df)
st.line_chart(results_df.set_index("Period")[["Floating Payment", "Fixed Payment"]])

# --------------------------
# 9. Liquidation Check
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")

liquidation_threshold = collateral_value_usd * LIQUIDATE_CF
st.write(f"Liquidation Threshold (at {LIQUIDATE_CF*100:.1f}%): ${liquidation_threshold:,.2f}")

if max_borrow_usd > liquidation_threshold:
    st.error("❌ Position exceeds liquidation threshold! Risk of liquidation.")
else:
    st.success("✅ Position is safe under current collateral factors.")
