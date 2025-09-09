import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.set_page_config(page_title="Compound Fixed Rate Swap", layout="wide")
st.title("Compound Fixed Rate Swap Simulator — Daily Floating Rates")
st.write("""
Fetches historical APRs, runs a backtest to predict future floating rates that vary daily,
automatically sets a fixed rate higher than the floating rates, simulates daily cashflows,
and checks for liquidation risk.
""")

# --------------------------
# 2. Collateral factors (hardcoded)
# --------------------------
BORROW_CF = 0.825
LIQUIDATE_CF = 0.88
LIQ_PENALTY = 0.07

# --------------------------
# 3. ETH price via Infura + Chainlink oracle
# --------------------------
INFURA_PROJECT_ID = "dfe34c8812444c0e8f1e4806789f58d6"  # 🔑 replace with your Infura project ID
INFURA_URL = f"https://mainnet.infura.io/v3/{INFURA_PROJECT_ID}"

CHAINLINK_ETH_USD = "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419"  # ETH/USD aggregator

@st.cache_data(ttl=300)
def get_eth_price_usd():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {
                "to": CHAINLINK_ETH_USD,
                "data": "0x50d25bcd"  # latestRoundData()
            },
            "latest"
        ]
    }
    r = requests.post(INFURA_URL, json=payload, timeout=10)
    r.raise_for_status()
    result = r.json()["result"]

    # latestRoundData returns (roundId, answer, startedAt, updatedAt, answeredInRound)
    # Each is 32 bytes (64 hex chars)
    answer_hex = result[2:66]  # skip 0x, take first 32 bytes
    price_int = int(answer_hex, 16)
    price = price_int / 1e8  # Chainlink returns with 8 decimals
    return price

try:
    eth_price = get_eth_price_usd()
    st.success(f"💰 Current ETH Price (USD via Infura/Chainlink): ${eth_price:,.2f}")
except Exception as e:
    st.error(f"Failed to fetch ETH price from Infura: {e}")
    eth_price = st.number_input("Enter ETH Price manually (USD)", min_value=500.0, value=2000.0, step=10.0)

# --------------------------
# 4. Fetch 1000 APR points from The Graph
# --------------------------
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"
headers = {"Content-Type": "application/json"}

query = """
{
  dailyMarketAccountings(
    first: 1000,
    where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" },
    orderBy: timestamp,
    orderDirection: asc
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

if df["borrowApr"].mean() > 1:
    df["borrowApr"] /= 100
    df["supplyApr"] /= 100

# 5. Display most recent 10 APRs (FIXED)
# --------------------------
st.subheader("📊 Most Recent 10 APRs")

df_last10 = df.sort_values("timestamp", ascending=False).head(10)  # take 10 most recent rows
df_last10 = df_last10.reset_index(drop=True)

st.dataframe(df_last10[["timestamp", "borrowApr", "supplyApr"]])

# --------------------------
# 6. Swap Simulator Inputs
# --------------------------
st.subheader("💡 Swap Simulator Settings")
eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
simulation_days = st.slider("Simulation Period (Days)", 1, 90, 30)

# --------------------------
# 7. Borrow capacity & liquidation
# --------------------------
collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF
liquidation_threshold = collateral_value_usd * LIQUIDATE_CF

st.write(f"🔒 Collateral Value: ${collateral_value_usd:,.2f}")
st.write(f"📉 Max Borrow Capacity: ${max_borrow_usd:,.2f}")
st.write(f"⚠️ Liquidation Threshold: ${liquidation_threshold:,.2f}")

# --------------------------
# 8. Backtest: floating & fixed rates
# --------------------------
st.subheader("🔮 Backtest for Floating & Fixed Rates")

def ar1_forecast_varying(series: pd.Series, n_days: int):
    mu = series.mean()
    phi = 0.8
    last = series.iloc[-1]
    forecasts = []
    cur = last
    rng = np.random.default_rng(seed=42)
    for _ in range(n_days):
        shock = rng.normal(scale=0.002)
        nxt = mu + phi * (cur - mu) + shock
        nxt = max(nxt, 0.0)
        forecasts.append(nxt)
        cur = nxt
    return np.array(forecasts)

predicted_floating_rates = ar1_forecast_varying(df["borrowApr"], simulation_days)
fixed_rate_annual = predicted_floating_rates.max() + 0.0005
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
        st.warning(f"⚠️ Absorb() called on Day {liquidated_day} due to LCF breach!")

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
