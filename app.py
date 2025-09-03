import streamlit as st
import requests
import pandas as pd

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Prototype")
st.write("This app shows Compound APR data, fetches ETH price from Polygon.io, "
         "and simulates a simple fixed–floating swap using ETH as collateral.")

# --------------------------
# 2. Collateral Factors (from Compound v3)
# --------------------------
BORROW_CF = 0.825   # 82.5%
LIQUIDATE_CF = 0.88 # 88.0%
LIQ_PENALTY = 0.07  # 7%

# --------------------------
# 3. Fetch ETH Price from Polygon.io
# --------------------------
API_KEY_POLYGON = "on0FmvftNux2r3sVEmDVr4mR6n9e0ZCc"

@st.cache_data(ttl=300)  # cache for 5 min
def get_eth_price_usd():
    url = f"https://api.polygon.io/v2/aggs/ticker/X:ETHUSD/prev?apiKey={API_KEY_POLYGON}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    return float(data["results"][0]["c"])  # closing price

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

# Convert to DataFrame
df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in data["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(entry["accounting"]["borrowApr"]) for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(entry["accounting"]["supplyApr"]) for entry in data["data"]["dailyMarketAccountings"]]
})

df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")

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
periods = st.slider("Number of Periods (months)", 1, 12, 6)

# --------------------------
# 6a. Backtest to suggest fixed rate
# --------------------------
# Take the max borrow APR of the last N periods as the suggested fixed rate
historical_borrow_aprs = df["borrowApr"].tail(periods).values
suggested_fixed_rate = max(historical_borrow_aprs)

# Display suggested fixed rate in input box
fixed_rate = st.number_input(
    "Fixed Rate (annual %)", 
    min_value=0.0, 
    value=suggested_fixed_rate*100, 
    step=0.1
)

# --------------------------
# Borrow capacity (USD)
# --------------------------
collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF

st.write(f"🔒 Collateral Value: ${collateral_value_usd:,.2f}")
st.write(f"📉 Max Borrow Capacity (using {BORROW_CF*100:.1f}% factor): ${max_borrow_usd:,.2f}")

# --------------------------
# Cashflows
# --------------------------
floating_rates = df["borrowApr"].tail(periods).values
fixed_payment = max_borrow_usd * (fixed_rate / 100) / 12  # monthly fixed

results = []
for i in range(periods):
    floating_payment = max_borrow_usd * floating_rates[i] / 12
    net_cashflow = fixed_payment - floating_payment
    results.append({
        "Period": i + 1,
        "Floating Rate": f"{}
