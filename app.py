import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Prototype — Daily Simulation")
st.write(
    "Shows recent APRs, runs a backtest to pick a fixed rate, simulates daily cashflows, "
    "and checks liquidation risk."
)

# --------------------------
# 2. Collateral Factors
# --------------------------
BORROW_CF = 0.825
LIQUIDATE_CF = 0.88

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

try:
    eth_price = get_eth_price_usd()
    st.success(f"💰 Current ETH Price (USD): ${eth_price:,.2f}")
except Exception:
    st.error("Failed to fetch ETH price from Polygon.io.")
    eth_price = st.number_input("Enter ETH Price manually (USD)", min_value=500.0, value=2000.0, step=10.0)

# --------------------------
# 4. Fetch APR Data
# --------------------------
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"
headers = {"Content-Type": "application/json"}

query = """
{
  dailyMarketAccountings(
    first: 100,
    where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" },
    orderBy: timestamp,
    orderDirection: desc
  ) {
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
df_recent = df.tail(10).copy()

if df_recent["borrowApr"].mean() > 1:
    df_recent["borrowApr"] /= 100.0
    df_recent["supplyApr"] /= 100.0

# --------------------------
# 5. Show recent APRs
# --------------------------
st.subheader("📊 Most Recent APR Data (Last 10 Days)")
st.line_chart(df_recent.set_index("timestamp")[["borrowApr", "supplyApr"]])
st.dataframe(df_recent.reset_index(drop=True))

# --------------------------
# 6. Forecast
# --------------------------
st.subheader("🔮 Backtest & Forecast")

margin = 0.001
backtest_fixed = df_recent["borrowApr"].max() + margin

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

# --------------------------
# 7. Swap Simulator
# --------------------------
st.subheader("💡 Fixed–Floating Swap Simulator (Daily)")

eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
days = st.slider("Number of Days", 1, 90, 30)

predicted_floating_rates = ar1_forecast(df_recent["borrowApr"], days)
fixed_rate_annual = max(backtest_fixed, predicted_floating_rates.max() + 0.0005)

fixed_rate_daily = (1 + fixed_rate_annual) ** (1/365) - 1
floating_rates_daily = (1 + predicted_floating_rates) ** (1/365) - 1

collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF
liquidation_threshold = collateral_value_usd * LIQUIDATE_CF

# Daily cashflows with cumulative
results = []
cumulative_net = 0.0
for i in range(days):
    floating_payment = max_borrow_usd * floating_rates_daily[i]
    fixed_payment = max_borrow_usd * fixed_rate_daily
    net = fixed_payment - floating_payment
    cumulative_net += net

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
# 8. Liquidation Check
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")

if max_borrow_usd > liquidation_threshold:
    st.error("❌ Position exceeds liquidation threshold! Risk of liquidation.")
else:
    st.success("✅ Position is safe under current collateral factors.")
