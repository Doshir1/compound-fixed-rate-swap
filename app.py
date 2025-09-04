import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Prototype — Time-varying Floating Forecast")
st.write(
    "Shows recent APRs (last 10), runs a simple backtest to pick a fixed rate, "
    "and forecasts a changing floating rate for the simulated periods (AR(1))."
)

# --------------------------
# 2. Collateral Factors
# --------------------------
BORROW_CF = 0.825   # 82.5%
LIQUIDATE_CF = 0.88 # 88.0%
LIQ_PENALTY = 0.07  # 7%

# --------------------------
# 3. Fetch ETH Price from Polygon.io
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
except Exception:
    st.error("Failed to fetch ETH price from Polygon.io.")
    eth_price = st.number_input("Enter ETH Price manually (USD)", min_value=500.0, value=2000.0, step=10.0)

# --------------------------
# 4. Fetch APR Data from The Graph (latest 100 entries)
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

# Convert to DataFrame
df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in data["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(entry["accounting"]["borrowApr"]) for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(entry["accounting"]["supplyApr"]) for entry in data["data"]["dailyMarketAccountings"]]
})

df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")  # oldest -> newest

# Keep only the 10 most recent APRs
df_recent = df.tail(10).copy()

# Safety: sometimes API returns % as 5.0 for 5% instead of 0.05.
# If values look > 1 on average, treat them as percents and convert.
if df_recent["borrowApr"].mean() > 1:
    df_recent["borrowApr"] = df_recent["borrowApr"] / 100.0
    df_recent["supplyApr"] = df_recent["supplyApr"] / 100.0

# --------------------------
# 5. Show Recent APRs
# --------------------------
st.subheader("📊 Most Recent APR Data (Last 10 Entries)")
st.line_chart(df_recent.set_index("timestamp")[["borrowApr", "supplyApr"]])
st.dataframe(df_recent.reset_index(drop=True))

# --------------------------
# 6. Backtest & Forecast (AR(1) simple)
# --------------------------
st.subheader("🔮 Backtest (fixed rate) & AR(1) forecast (time-varying floating)")

# Backtest-derived fixed rate: max historical recent APR + margin
margin = 0.001  # 0.1% absolute (in decimal)
backtest_fixed = df_recent["borrowApr"].max() + margin

# Simple AR(1) forecasting for 'periods' steps:
def ar1_forecast(series: pd.Series, n_steps: int):
    """
    Very simple AR(1) forecast:
      - mu = series.mean()
      - phi = lag-1 autocorrelation (clipped)
      - forecast recursively: r_{t+1} = mu + phi*(r_t - mu)
    Returns np.array of length n_steps (forecasts).
    """
    vals = series.values
    if len(vals) < 2:
        # not enough data -> flat forecast at last observed or mean
        start = float(series.iloc[-1]) if len(vals) == 1 else float(series.mean() if len(vals) else 0.0)
        return np.array([start for _ in range(n_steps)])
    mu = float(series.mean())
    # compute lag-1 autocorrelation (phi)
    centered = vals - mu
    num = np.sum(centered[1:] * centered[:-1])
    den = np.sum(centered[:-1] ** 2) if np.sum(centered[:-1] ** 2) != 0 else 1e-12
    phi = num / den
    # Clip phi to a safe range to avoid explosive forecasts
    phi = float(np.clip(phi, -0.99, 0.99))
    last = float(vals[-1])
    forecasts = []
    cur = last
    for _ in range(n_steps):
        nxt = mu + phi * (cur - mu)
        # prevent negative rates
        nxt = max(nxt, 0.0)
        forecasts.append(nxt)
        cur = nxt
    return np.array(forecasts)

# --------------------------
# 7. Swap Simulator UI
# --------------------------
st.subheader("💡 Fixed–Floating Swap Simulator")
eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
periods = st.slider("Number of Periods (months)", 1, 12, 6)

# Forecast the floating rate across 'periods' future periods (time-varying)
predicted_floating_rates = ar1_forecast(df_recent["borrowApr"], periods)

# Ensure fixed rate is greater than any predicted floating rate too
fixed_rate = max(backtest_fixed, predicted_floating_rates.max() + 0.0005)  # small extra buffer
st.write(f"📈 Fixed Rate (backtest-based, annual %): {fixed_rate*100:.2f}%")

# Also show predicted floating rate series
pred_df = pd.DataFrame({
    "Period": np.arange(1, periods + 1),
    "Predicted Floating APR": predicted_floating_rates
})
st.write("🌊 Predicted (time-varying) floating APRs by period")
st.table((pred_df.assign(**{"Predicted Floating APR (%)": pred_df["Predicted Floating APR"]*100})
          [["Period", "Predicted Floating APR (%)"]]).set_index("Period"))

# --------------------------
# 8. Borrow capacity (USD)
# --------------------------
collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF

st.write(f"🔒 Collateral Value: ${collateral_value_usd:,.2f}")
st.write(f"📉 Max Borrow Capacity (using {BORROW_CF*100:.1f}% factor): ${max_borrow_usd:,.2f}")

# --------------------------
# 9. Cashflow Simulation using time-varying predicted floating rates
# --------------------------
fixed_payments = [max_borrow_usd * fixed_rate / 12.0 for _ in range(periods)]
floating_payments = [max_borrow_usd * r / 12.0 for r in predicted_floating_rates]

results = []
for i in range(periods):
    net_cashflow = fixed_payments[i] - floating_payments[i]
    results.append({
        "Period": i + 1,
        "Predicted Floating APR (%)": f"{predicted_floating_rates[i]*100:.4f}",
        "Floating Payment (USD)": floating_payments[i],
        "Fixed Payment (USD)": fixed_payments[i],
        "Net Cashflow (USD)": net_cashflow
    })

results_df = pd.DataFrame(results)
st.dataframe(results_df)
st.line_chart(results_df.set_index("Period")[["Floating Payment (USD)", "Fixed Payment (USD)"]])

# --------------------------
# 10. Liquidation Check
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")
liquidation_threshold = collateral_value_usd * LIQUIDATE_CF
st.write(f"Liquidation Threshold (at {LIQUIDATE_CF*100:.1f}%): ${liquidation_threshold:,.2f}")

if max_borrow_usd > liquidation_threshold:
    st.error("❌ Position exceeds liquidation threshold! Risk of liquidation.")
else:
    st.success("✅ Position is safe under current collateral factors.")
