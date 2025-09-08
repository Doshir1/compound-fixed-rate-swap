import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Simulator — Daily Floating Rates (No web3)")
st.write("""
Fetches historical APRs, collateral factors, ETH/USDC price, 
runs a backtest to predict floating rates, 
automatically sets a fixed rate, simulates cashflows, and checks for liquidation.
""")

# --------------------------
# 2. Fetch asset factors from The Graph
# --------------------------
API_KEY_GRAPH = "3b6cc500833cb7c07f3eb2e97bc88709"
GRAPH_URL = f"https://gateway.thegraph.com/api/{API_KEY_GRAPH}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"

@st.cache_data(ttl=600)
def get_asset_factors():
    query = """
    {
      assets(where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3", symbol: "ETH" }) {
        borrowCollateralFactor
        liquidateCollateralFactor
        liquidationFactor
      }
    }
    """
    r = requests.post(GRAPH_URL, json={"query": query})
    r.raise_for_status()
    asset = r.json()["data"]["assets"][0]
    return {
        "borrow_cf": float(asset["borrowCollateralFactor"]) / 1e18,
        "liquidate_cf": float(asset["liquidateCollateralFactor"]) / 1e18,
        "liquidation_factor": float(asset["liquidationFactor"]) / 1e18,
    }

factors = get_asset_factors()
BORROW_CF = factors["borrow_cf"]
LIQUIDATE_CF = factors["liquidate_cf"]

# --------------------------
# 3. Fetch ETH/USDC price from Chainlink
# --------------------------
@st.cache_data(ttl=300)
def get_eth_price_usdc():
    ethusd = requests.get(
        "https://api.redstone.finance/prices?symbol=ETH&provider=chainlink&limit=1"
    ).json()[0]["value"]

    usdcusd = requests.get(
        "https://api.redstone.finance/prices?symbol=USDC&provider=chainlink&limit=1"
    ).json()[0]["value"]

    return ethusd / usdcusd

try:
    eth_price = get_eth_price_usdc()
    st.success(f"💰 Current ETH Price (USDC): {eth_price:,.2f}")
except Exception:
    st.error("Failed to fetch ETH/USDC price.")
    eth_price = st.number_input("Enter ETH Price manually (USDC)", min_value=500.0, value=2000.0, step=10.0)

# --------------------------
# 4. Fetch 1000 APR points
# --------------------------
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

response = requests.post(GRAPH_URL, json={"query": query})
data = response.json()

df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in data["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(entry["accounting"]["borrowApr"]) for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(entry["accounting"]["supplyApr"]) for entry in data["data"]["dailyMarketAccountings"]]
})

df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")  # Oldest → newest

# Convert to decimals if necessary
if df["borrowApr"].mean() > 1:
    df["borrowApr"] /= 100
    df["supplyApr"] /= 100

# --------------------------
# 5. Display most recent 10 days
# --------------------------
today = pd.Timestamp.today().normalize()
last_10_days = today - pd.to_timedelta(np.arange(10), unit='d')
df["date_only"] = df["timestamp"].dt.normalize()
df_last10 = df[df["date_only"].isin(last_10_days)]
if len(df_last10) < 10:
    df_last10 = df.tail(10)
df_last10 = df_last10.sort_values("timestamp", ascending=False)
st.subheader("📊 Most Recent 10 APRs (Last 10 Days)")
st.dataframe(df_last10[["timestamp", "borrowApr", "supplyApr"]].reset_index(drop=True))

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
# 8. Backtest & Forecast Floating Rates
# --------------------------
st.subheader("🔮 Backtest for Floating & Fixed Rates")

def ar1_forecast_varying(series: pd.Series, n_days: int):
    mu = series.mean()
    phi = 0.8  # moderate autocorrelation
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
