import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Simulator — Full Daily Backtest")
st.write("""
This app fetches historical Compound APR data, runs a backtest to predict future floating rates, 
automatically sets a fixed rate higher than predicted floating rates, simulates daily cashflows, 
and checks for liquidation risk.
""")

# --------------------------
# 2. Collateral factors
# --------------------------
BORROW_CF = 0.825
LIQUIDATE_CF = 0.88

# --------------------------
# 3. Fetch ETH price from Polygon
# --------------------------
API_KEY_POLYGON = "on0FmvftNux2r3sVEmDVr4mR6n9e0ZCc"

@st.cache_data(ttl=300)
def get_eth_price_usd():
    url = f"https://api.polygon.io/v2/aggs/ticker/X:ETHUSD/prev?apiKey={API_KEY_POLYGON}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    return float(data["results"][0]["c"])

try:
    eth_price = get_eth_price_usd()
    st.success(f"💰 Current ETH Price (USD): ${eth_price:,.2f}")
except Exception:
    st.error("Failed to fetch ETH price from Polygon.io.")
    eth_price = st.number_input("Enter ETH Price manually (USD)", min_value=500.0, value=2000.0, step=10.0)

# --------------------------
# 4. Fetch 1000 APR data points from Compound via The Graph
# --------------------------
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"
headers = {"Content-Type": "application/json"}

query = """
{
  dailyMarketAccountings(first: 1000, where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" }, orderBy: timestamp, orderDirection: asc) {
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
df = df.sort_values("timestamp")  # Oldest to newest

# Convert to decimals if necessary
if df["borrowApr"].mean() > 1:
    df["borrowApr"] /= 100
    df["supplyApr"] /= 100

# --------------------------
# 5. Display recent 10 APRs & full chart
# --------------------------
df_recent = df.tail(10).copy()
st.subheader("📊 Most Recent 10 APR Data Points")
st.dataframe(df_recent.reset_index(drop=True))

st.subheader("📈 Historical APR Chart (Full 1000 Days)")
st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])

# --------------------------
# 6. Swap Simulator Inputs
# --------------------------
st.subheader("💡 Swap Simulator Settings")

eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
simulation_days = st.slider("Simulation Period (Days)", 1, 90, 30)

# --------------------------
# 7. Borrow capacity and liquidation
# --------------------------
collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF
liquidation_threshold = collateral_value_usd * LIQUIDATE_CF

st.write(f"🔒 Collateral Value: ${collateral_value_usd:,.2f}")
st.write(f"📉 Max Borrow Capacity: ${max_borrow_usd:,.2f}")
st.write(f"⚠️ Liquidation Threshold: ${liquidation_threshold:,.2f}")

# --------------------------
# 8. Backtest to compute fixed & floating rates
# --------------------------
st.subheader("🔮 Backtest to Determine Rates")

# Function: AR(1) forecast per period
def ar1_forecast(series: pd.Series, n_steps: int):
    vals = series.values
    if len(vals) < 2:
        return np.array([series.iloc[-1]] * n_steps)
    mu = float(series.mean())
    centered = vals - mu
    num = np.sum(centered[1:] * centered[:-1])
    den = np.sum(centered[:-1] ** 2) or 1e-12
    phi = np.clip(num / den, -0.99, 0.99)
    last = float(vals[-1])
    forecasts = []
    cur = last
    for _ in range(n_steps):
        nxt = mu + phi * (cur - mu)
        nxt = max(nxt, 0.0)
        forecasts.append(nxt)
        cur = nxt
    return np.array(forecasts)

# Backtest: split historical data into chunks equal to simulation period
chunk_size = simulation_days
num_chunks = len(df) // chunk_size
floating_predictions = []

for i in range(num_chunks):
    start_idx = i * chunk_size
    end_idx = start_idx + chunk_size
    if end_idx > len(df):
        break
    period_data = df["borrowApr"].iloc[start_idx:end_idx]
    predicted = ar1_forecast(period_data, simulation_days)
    floating_predictions.append(predicted)

# Take the last predicted period as future floating rates
predicted_floating_rates = floating_predictions[-1]

# Fixed rate = max of predicted floating + small margin
fixed_rate_annual = max(predicted_floating_rates.max() + 0.0005, predicted_floating_rates.max())
fixed_rate_daily = (1 + fixed_rate_annual) ** (1/365) - 1
floating_rates_daily = (1 + predicted_floating_rates) ** (1/365) - 1

st.write(f"📈 Fixed Rate (annual): {fixed_rate_annual*100:.2f}%")
st.write(f"➡️ Daily Fixed Rate: {fixed_rate_daily*100:.4f}%")

# --------------------------
# 9. Daily Cashflow Simulation
# --------------------------
st.subheader("📑 Daily Cashflows & Cumulative Net")

results = []
cumulative_net = 0.0
liquidated_day = None

for i in range(simulation_days):
    floating_payment = max_borrow_usd * floating_rates_daily[i]
    fixed_payment = max_borrow_usd * fixed_rate_daily
    net = fixed_payment - floating_payment
    cumulative_net += net

    effective_debt = max_borrow_usd - cumulative_net
    if effective_debt > liquidation_threshold and liquidated_day is None:
        liquidated_day = i + 1
        # absorb() placeholder
        st.warning(f"Absorb() called on Day {liquidated_day} due to LCF breach!")

    results.append({
        "Day": i + 1,
        "Floating APR (annual %)": f"{predicted_floating_rates[i]*100:.4f}",
        "Floating Payment (USD)": floating_payment,
        "Fixed Payment (USD)": fixed_payment,
        "Net Cashflow (USD)": net,
        "Cumulative Net Cashflow (USD)": cumulative_net
    })

results_df = pd.DataFrame(results)
st.dataframe(results_df)
st.line_chart(results_df.set_index("Day")[["Floating Payment (USD)", "Fixed Payment (USD)"]])

# --------------------------
# 10. Final Liquidation Check
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")
if liquidated_day:
    st.error(f"❌ Liquidation triggered on Day {liquidated_day}!")
else:
    st.success("✅ No liquidation during the simulation horizon.")
