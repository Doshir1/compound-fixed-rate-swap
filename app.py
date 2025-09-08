import streamlit as st
import requests
import pandas as pd
import json
from web3 import Web3

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Simulator — Daily Floating Rates")
st.write("""
Now using on-chain ETH/USDC price and collateral factors directly from Compound v3 (Ethereum mainnet).
Fetches historical APRs, runs a backtest to predict daily floating rates,
automatically sets a fixed rate higher than floating rates, simulates daily cashflows,
and checks for liquidation risk.
""")

# --------------------------
# 2. On-chain connection
# --------------------------
INFURA_URL = "https://mainnet.infura.io/v3/dfe34c8812444c0e8f1e4806789f58d6"
web3 = Web3(Web3.HTTPProvider(INFURA_URL))

if not web3.is_connected():
    st.error("❌ Could not connect to Ethereum Mainnet.")
else:
    st.success("✅ Connected to Ethereum Mainnet")

# --------------------------
# 3. Comet contract setup
# --------------------------
comet_address = Web3.to_checksum_address("0xc3d688B66703497DAA19211EEdff47f25384cdc3")  # USDC Comet
comet_abi = json.loads("""
[
  {
    "inputs": [
      { "internalType": "address", "name": "asset", "type": "address" }
    ],
    "name": "getAssetInfoByAddress",
    "outputs": [
      {
        "components": [
          { "internalType": "uint8", "name": "offset", "type": "uint8" },
          { "internalType": "address", "name": "asset", "type": "address" },
          { "internalType": "address", "name": "priceFeed", "type": "address" },
          { "internalType": "uint64", "name": "scale", "type": "uint64" },
          { "internalType": "uint64", "name": "borrowCollateralFactor", "type": "uint64" },
          { "internalType": "uint64", "name": "liquidateCollateralFactor", "type": "uint64" },
          { "internalType": "uint64", "name": "liquidationFactor", "type": "uint64" },
          { "internalType": "uint128", "name": "supplyCap", "type": "uint128" }
        ],
        "internalType": "struct AssetInfo",
        "name": "",
        "type": "tuple"
      }
    ],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [
      { "internalType": "address", "name": "priceFeed", "type": "address" }
    ],
    "name": "getPrice",
    "outputs": [
      { "internalType": "uint128", "name": "", "type": "uint128" }
    ],
    "stateMutability": "view",
    "type": "function"
  }
]
""")
comet = web3.eth.contract(address=comet_address, abi=comet_abi)

# ETH (WETH) address
eth_address = Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")

# --------------------------
# 4. Fetch ETH price + CFs dynamically
# --------------------------
def get_eth_data():
    asset_info = comet.functions.getAssetInfoByAddress(eth_address).call()
    borrow_cf = asset_info[4] / 1e18
    liquidate_cf = asset_info[5] / 1e18
    liquidation_factor = asset_info[6] / 1e18
    price_feed = asset_info[2]

    # Get ETH price in USDC (scaled by 1e8)
    raw_price = comet.functions.getPrice(price_feed).call()
    eth_price_usdc = raw_price / 1e8

    return borrow_cf, liquidate_cf, liquidation_factor, eth_price_usdc

try:
    BORROW_CF, LIQUIDATE_CF, LIQ_FACTOR, eth_price = get_eth_data()
    st.success(f"💰 Current ETH Price: {eth_price:,.2f} USDC")
    st.write(f"- Borrow Collateral Factor: {BORROW_CF*100:.2f}%")
    st.write(f"- Liquidate Collateral Factor: {LIQUIDATE_CF*100:.2f}%")
    st.write(f"- Liquidation Penalty: {(1 - LIQ_FACTOR)*100:.2f}%")
except Exception as e:
    st.error(f"Failed to fetch on-chain ETH data: {e}")
    eth_price = st.number_input("Enter ETH Price manually (USDC)", min_value=500.0, value=2000.0, step=10.0)
    BORROW_CF, LIQUIDATE_CF, LIQ_FACTOR = 0.825, 0.88, 0.95

# --------------------------
# 5. Fetch 1000 APR points
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

df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in data["data"]["dailyMarketAccountings"]],
    "borrowApr": [float(entry["accounting"]["borrowApr"]) for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [float(entry["accounting"]["supplyApr"]) for entry in data["data"]["dailyMarketAccountings"]]
})
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("timestamp")

# Ensure APRs are decimals
if df["borrowApr"].mean() > 1:
    df["borrowApr"] /= 100
    df["supplyApr"] /= 100

# --------------------------
# 6. Show most recent 10 calendar days
# --------------------------
today = pd.Timestamp.today().normalize()
last_10_days = pd.date_range(end=today, periods=10)
df["date_only"] = df["timestamp"].dt.normalize()
df_last10 = df[df["date_only"].isin(last_10_days)].sort_values("timestamp", ascending=False)

if df_last10.empty or len(df_last10) < 10:
    df_last10 = df.tail(10).sort_values("timestamp", ascending=False)

st.subheader("📊 Most Recent 10 Days of APRs")
st.dataframe(df_last10[["timestamp", "borrowApr", "supplyApr"]].reset_index(drop=True))

st.subheader("📈 Historical APR Chart (Full 1000 Days)")
st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])

# --------------------------
# 7. Swap Simulator Inputs
# --------------------------
st.subheader("💡 Swap Simulator Settings")
eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
simulation_days = st.slider("Simulation Period (Days)", 1, 90, 30)

# --------------------------
# 8. Borrow capacity and liquidation
# --------------------------
collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF
liquidation_threshold = collateral_value_usd * LIQUIDATE_CF

st.write(f"🔒 Collateral Value: {collateral_value_usd:,.2f} USDC")
st.write(f"📉 Max Borrow Capacity: {max_borrow_usd:,.2f} USDC")
st.write(f"⚠️ Liquidation Threshold: {liquidation_threshold:,.2f} USDC")

# --------------------------
# 9. Backtest & Forecast Floating Rates
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
# 10. Daily Cashflow Simulation
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
        "Floating Payment (USDC)": floating_payment,
        "Fixed Payment (USDC)": fixed_payment,
        "Net Cashflow (USDC)": net,
        "Cumulative Net Cashflow (USDC)": cumulative_net
    })

results_df = pd.DataFrame(results)
st.dataframe(results_df)
st.line_chart(results_df.set_index("Day")[["Floating Payment (USDC)", "Fixed Payment (USDC)"]])

# --------------------------
# 11. Final Liquidation Check
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")
if liquidated_day:
    st.error(f"❌ Liquidation triggered on Day {liquidated_day}!")
else:
    st.success("✅ No liquidation during the simulation horizon.")
