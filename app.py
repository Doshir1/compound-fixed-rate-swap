import os
import math
import requests
import pandas as pd
import streamlit as st
from web3 import Web3
!pip install web3
# =========================
# 0) Page Setup
# =========================
st.set_page_config(page_title="Compound v3 Swap Simulator", layout="wide")
st.title("Compound v3 Swap Simulator")
st.caption("ETH collateral → USDC borrow. Fixed-vs-floating swap backtest using Compound v3 data.")

# Addresses (Compound v3 USDC Comet + WETH)
COMET_USDC_MAINNET = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
WETH_MAINNET       = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

# Minimal ABI for getAssetInfoByAddress
COMET_MIN_ABI = [
    {
        "inputs": [{"internalType":"address","name":"asset","type":"address"}],
        "name":"getAssetInfoByAddress",
        "outputs":[
            {"components":[
                {"internalType":"uint8","name":"offset","type":"uint8"},
                {"internalType":"address","name":"asset","type":"address"},
                {"internalType":"address","name":"priceFeed","type":"address"},
                {"internalType":"uint64","name":"scale","type":"uint64"},
                {"internalType":"uint64","name":"borrowCollateralFactor","type":"uint64"},
                {"internalType":"uint64","name":"liquidateCollateralFactor","type":"uint64"},
                {"internalType":"uint64","name":"liquidationFactor","type":"uint64"},
                {"internalType":"uint128","name":"supplyCap","type":"uint128"}
            ], "internalType":"struct AssetInfo","name":"","type":"tuple"}
        ],
        "stateMutability":"view",
        "type":"function"
    }
]

# =========================
# 1) The Graph Data
# =========================
graph_api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
subgraph_id = "5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"
url = f"https://gateway.thegraph.com/api/{graph_api_key}/subgraphs/id/{subgraph_id}"

query = """
{
  dailyMarketAccountings(first: 730, orderBy: timestamp, orderDirection: asc,
    where: { market: "0xc3d688b66703497daa19211eedff47f25384cdc3" }) {
    timestamp
    accounting { borrowApr supplyApr }
  }
}
"""

st.info("Fetching APR history from The Graph...")
resp = requests.post(url, json={"query": query}, headers={"Content-Type": "application/json"})
raw = resp.json()["data"]["dailyMarketAccountings"]

df = pd.DataFrame({
    "timestamp": [int(x["timestamp"]) for x in raw],
    "borrowApr_annual": [float(x["accounting"]["borrowApr"]) for x in raw],
    "supplyApr_annual": [float(x["accounting"]["supplyApr"]) for x in raw],
})
df["date"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("date").reset_index(drop=True)

# =========================
# 2) Auto Fixed Rate (Backtest)
# =========================
mean_b = df["borrowApr_annual"].mean()
std_b = df["borrowApr_annual"].std()
fixed_rate_annual = mean_b + 0.5 * std_b   # automatic rule
seconds_per_year = 365 * 24 * 3600
fixed_rate_per_day = (1 + fixed_rate_annual) ** (1/365) - 1

st.subheader("📌 Fixed Rate Determined from Backtest")
st.write(f"Suggested fixed rate = mean + ½·std = **{fixed_rate_annual*100:.2f}% annual**")
st.write(f"Equivalent to **{fixed_rate_per_day:.6f} per day**")

# =========================
# 3) Collateral Factors via Infura
# =========================
infura_url = "https://mainnet.infura.io/v3/dfe34c8812444c0e8f1e4806789f58d6"
w3 = Web3(Web3.HTTPProvider(infura_url))
comet = w3.eth.contract(address=w3.to_checksum_address(COMET_USDC_MAINNET), abi=COMET_MIN_ABI)
info = comet.functions.getAssetInfoByAddress(w3.to_checksum_address(WETH_MAINNET)).call()

borrow_cf = info[4] / 1e18
liq_cf    = info[5] / 1e18
liq_factor= info[6] / 1e18
liq_penalty = 1 - liq_factor

st.subheader("📌 Collateral Parameters (from Comet)")
col = st.columns(3)
col[0].metric("Borrow CF", f"{borrow_cf*100:.1f}%")
col[1].metric("Liquidate CF", f"{liq_cf*100:.1f}%")
col[2].metric("Penalty", f"{liq_penalty*100:.1f}%")

# =========================
# 4) User Inputs: ETH collateral
# =========================
st.subheader("💰 Collateral & Borrowing")
eth_collateral = st.number_input("ETH collateral amount", min_value=0.1, value=10.0, step=0.1)
eth_price = st.number_input("ETH price (USD)", min_value=500.0, value=3000.0, step=50.0)

collateral_usd = eth_collateral * eth_price
max_borrow_usd = collateral_usd * borrow_cf

borrow_usd = st.number_input("Borrow amount (USDC)", min_value=100.0, max_value=float(max_borrow_usd), value=round(max_borrow_usd*0.9,2), step=100.0)
st.write(f"- Collateral value: **${collateral_usd:,.2f}**")
st.write(f"- Max borrow allowed: **${max_borrow_usd:,.2f}**")

# =========================
# 5) Simulation (daily)
# =========================
st.subheader("📊 Swap Simulation (Daily Cashflows)")
sim_days = st.slider("Simulation horizon (days)", 30, 365, 180)

hist = df.tail(sim_days).copy()
hist["borrow_rate_daily"] = (1 + hist["borrowApr_annual"]) ** (1/365) - 1

outstanding = borrow_usd
rows = []
cum_net = 0

for i, row in hist.iterrows():
    day = row["date"].date()
    rf = float(row["borrow_rate_daily"])
    fixed_pay = borrow_usd * fixed_rate_per_day
    float_pay = outstanding * rf
    net = fixed_pay - float_pay
    cum_net += net

    outstanding *= (1 + rf)
    liq_threshold = liq_cf * collateral_usd
    breach = outstanding > liq_threshold

    rows.append({
        "date": day,
        "float_interest": float_pay,
        "fixed_payment": fixed_pay,
        "net_cashflow": net,
        "cum_net_cashflow": cum_net,
        "outstanding_debt": outstanding,
        "liq_threshold": liq_threshold,
        "ltv": outstanding / collateral_usd,
        "liquidated": breach
    })

sim = pd.DataFrame(rows)

st.dataframe(sim.tail(10))
st.line_chart(sim.set_index("date")[["fixed_payment","float_interest"]])
st.line_chart(sim.set_index("date")[["cum_net_cashflow"]])
st.line_chart(sim.set_index("date")[["outstanding_debt","liq_threshold"]])

any_liq = sim["liquidated"].any()
st.warning("⚠️ Liquidation would occur!" if any_liq else "✅ Position remains healthy")
