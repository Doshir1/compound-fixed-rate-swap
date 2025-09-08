import streamlit as st
import requests
import pandas as pd
import numpy as np
from eth_abi import encode_abi, decode_abi

# --------------------------
# 1. Page setup
# --------------------------
st.set_page_config(page_title="Compound Fixed Rate Swap", layout="wide")
st.title("Compound Fixed Rate Swap Simulator — Mainnet ETH/USDC")
st.write("""
This app connects to Ethereum mainnet (Compound v3 Comet),
fetches historical APRs from The Graph, runs a backtest to predict
daily floating rates, automatically sets a fixed rate, simulates cashflows,
and checks liquidation risk using real collateral factors.
""")

# --------------------------
# 2. Infura Connection
# --------------------------
INFURA_URL = "https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID"  # Replace with your project ID

# Simple connectivity test
try:
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 1
    }
    response = requests.post(INFURA_URL, json=payload)
    result = response.json()
    if response.status_code == 200 and "result" in result:
        st.success(f"✅ Connected to Ethereum Mainnet via Infura (latest block: {int(result['result'],16)})")
    else:
        st.error(f"❌ Failed to connect to Ethereum via Infura: {result}")
        st.stop()
except Exception as e:
    st.error(f"❌ Error connecting to Infura: {e}")
    st.stop()

# --------------------------
# 3. Fetch Comet Collateral Factors (ETH/WETH)
# --------------------------
comet_address = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
eth_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

# getAssetInfoByAddress(address) function selector
function_selector = "0x59f4e7ff"
encoded_param = encode_abi(['address'], [eth_address]).hex()
data = function_selector + encoded_param

payload = {
    "jsonrpc": "2.0",
    "method": "eth_call",
    "params": [{"to": comet_address, "data": data}, "latest"],
    "id": 1
}
response = requests.post(INFURA_URL, json=payload)
result_hex = response.json()["result"]

# Decode the returned tuple
decoded = decode_abi(
    ['uint8','address','address','uint64','uint64','uint64','uint64','uint128'],
    bytes.fromhex(result_hex[2:])
)
borrow_cf = decoded[4] / 1e18
liquidate_cf = decoded[5] / 1e18
liquidation_factor = decoded[6] / 1e18
price_feed_address = decoded[2]

st.subheader("📊 ETH Collateral Factors (from Comet)")
st.write(f"- Borrow Collateral Factor: {borrow_cf*100:.2f}%")
st.write(f"- Liquidate Collateral Factor: {liquidate_cf*100:.2f}%")
st.write(f"- Liquidation Penalty: {(1 - liquidation_factor)*100:.2f}%")

# --------------------------
# 4. Fetch ETH/USD Price (via Chainlink)
# --------------------------
# latestRoundData() selector
function_selector_price = "0x50d25bcd"
payload = {
    "jsonrpc": "2.0",
    "method": "eth_call",
    "params": [{"to": price_feed_address, "data": function_selector_price}, "latest"],
    "id": 1
}
response = requests.post(INFURA_URL, json=payload)
result_hex = response.json()["result"]

# Decode price (answer is 2nd 32-byte slot)
answer = int(result_hex[66:130], 16)
eth_price = answer / 1e8  # Chainlink ETH/USD has 8 decimals
st.success(f"💰 Current ETH Price (USDC): ${eth_price:,.2f}")

# --------------------------
# 5. Fetch Historical APRs from The Graph
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

st.subheader("📊 Most Recent 10 APRs (Last 10 Days)")
today = pd.Timestamp.today().normalize()
last_10_days = today - pd.to_timedelta(np.arange(10), unit="d")
df["date_only"] = df["timestamp"].dt.normalize()
df_last10 = df[df["date_only"].isin(last_10_days)]
if len(df_last10) < 10:
    df_last10 = df.tail(10)
df_last10 = df_last10.sort_values("timestamp", ascending=False)
st.dataframe(df_last10[["timestamp", "borrowApr", "supplyApr"]].reset_index(drop=True))

st.subheader("📈 Historical APR Chart (1000 Days)")
st.line_chart(df.set_index("timestamp")[["borrowApr", "supplyApr"]])

# --------------------------
# 6. Swap Simulator Settings
# --------------------------
st.subheader("💡 Swap Simulator Settings")
eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
simulation_days = st.slider("Simulation Period (Days)", 1, 90, 30)
collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * borrow_cf
liquidation_threshold = collateral_value_usd * liquidate_cf
st.write(f"🔒 Collateral Value: ${collateral_value_usd:,.2f}")
st.write(f"📉 Max Borrow Capacity: ${max_borrow_usd:,.2f}")
st.write(f"⚠️ Liquidation Threshold: ${liquidation_threshold:,.2f}")

# --------------------------
# 7. Backtest: Floating & Fixed Rates
# --------------------------
def ar1_forecast(series: pd.Series, n_days: int):
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

predicted_floating_rates = ar1_forecast(df["borrowApr"], simulation_days)
fixed_rate_annual = predicted_floating_rates.max() + 0.0005
fixed_rate_daily = (1 + fixed_rate_annual) ** (1/365) - 1
floating_rates_daily = (1 + predicted_floating_rates) ** (1/365) - 1

st.subheader("🔮 Backtest Results")
st.write(f"📈 Fixed Rate (annual): {fixed_rate_annual*100:.2f}%")
st.write(f"➡️ Fixed Rate (daily): {fixed_rate_daily*100:.4f}%")

# --------------------------
# 8. Cashflow Simulation
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
# 9. Final Liquidation Check
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")
if liquidated_day:
    st.error(f"❌ Liquidation triggered on Day {liquidated_day}!")
else:
    st.success("✅ No liquidation during the simulation horizon.")
