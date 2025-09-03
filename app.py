import os
import math
import json
import requests
import pandas as pd
import streamlit as st

# =========================
# 0) Page + constants
# =========================
st.set_page_config(page_title="Compound v3 Fixed-Rate Swap Backtester", layout="wide")
st.title("Compound v3 Fixed-Rate Swap Backtester")
st.caption("Pulls APRs from The Graph; lets you backtest a fixed rate, size a borrow vs ETH collateral, and simulate liquidation risk & swap cashflows.")

# USDC Comet (mainnet) and WETH addresses
COMET_USDC_MAINNET = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"
WETH_MAINNET       = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

# Minimal ABI for getAssetInfoByAddress (Compound v3 Comet)
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
# 1) Inputs & data fetch
# =========================
st.sidebar.header("Data Settings")

# Your Graph API key (required)
graph_api_key = st.sidebar.text_input(
    "Graph API Key (required)",
    value="3b6cc500833cb7c07f3eb2e97bc88709",
    type="password",
)

# How many days of history to fetch
lookback_days = st.sidebar.slider("History window (days)", 90, 730, 365, help="Use at least ~365–730 for a decent backtest.")
subgraph_id = "5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"  # community Compound v3 subgraph id you used
market_addr = COMET_USDC_MAINNET.lower()

if not graph_api_key:
    st.error("Please enter your Graph API key in the sidebar.")
    st.stop()

thegraph_url = f"https://gateway.thegraph.com/api/{graph_api_key}/subgraphs/id/{subgraph_id}"

# GraphQL: get recent daily market accounting for the USDC market
# We'll fetch up to 1000 days and then trim to 'lookback_days'
query = """
{
  dailyMarketAccountings(first: 1000, orderBy: timestamp, orderDirection: desc,
    where: { market: "0xc3d688b66703497daa19211eedff47f25384cdc3" }) {
    timestamp
    accounting { borrowApr supplyApr }
  }
}
"""

with st.spinner("Fetching APR history from The Graph..."):
    r = requests.post(thegraph_url, json={"query": query}, headers={"Content-Type": "application/json"})
    if r.status_code != 200:
        st.error(f"GraphQL error {r.status_code}: {r.text}")
        st.stop()
    data = r.json()
    if "data" not in data or "dailyMarketAccountings" not in data["data"]:
        st.error("No data returned from subgraph. Check API key/subgraph id/market address.")
        st.stop()

raw = data["data"]["dailyMarketAccountings"]
if len(raw) == 0:
    st.error("No rows returned from subgraph.")
    st.stop()

df = pd.DataFrame({
    "timestamp": [int(x["timestamp"]) for x in raw],
    "borrowApr_annual": [float(x["accounting"]["borrowApr"]) for x in raw],
    "supplyApr_annual": [float(x["accounting"]["supplyApr"]) for x in raw],
})
df["date"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.sort_values("date").reset_index(drop=True)

# Use last N days
df = df.tail(lookback_days).reset_index(drop=True)

st.subheader("APR History")
st.write("Borrow vs Supply APR (annualized):")
st.line_chart(df.set_index("date")[["borrowApr_annual", "supplyApr_annual"]])

st.caption(f"Rows: {len(df)}  •  From {df['date'].iloc[0].date()} to {df['date'].iloc[-1].date()}")

# =========================
# 2) Backtest fixed rate choice
# =========================
st.subheader("1) Pick a Fixed Rate (Backtest)")

# Simple statistics
mean_b = df["borrowApr_annual"].mean()
median_b = df["borrowApr_annual"].median()
std_b = df["borrowApr_annual"].std()
p95_b = df["borrowApr_annual"].quantile(0.95)

colA, colB, colC, colD = st.columns(4)
colA.metric("Mean borrow APR", f"{mean_b*100:.2f}%")
colB.metric("Median borrow APR", f"{median_b*100:.2f}%")
colC.metric("Std dev (abs)", f"{std_b*100:.2f}%")
colD.metric("95th percentile", f"{p95_b*100:.2f}%")

st.write(
    "- A simple conservative choice is **mean + ½·std**. "
    "You can adjust this to match your target risk/return."
)

suggested_fixed = float(mean_b + 0.5 * std_b)
fixed_rate_annual = st.number_input(
    "Choose your fixed annual rate (decimal, e.g. 0.06 = 6%)",
    min_value=0.0, max_value=1.0, value=round(suggested_fixed, 4), step=0.001,
    help="This is the fixed rate you’ll pay (if you borrow) or receive (if you lend) in the swap."
)

# Convert fixed to per-second and per-day
seconds_per_year = 365 * 24 * 3600
fixed_rate_per_sec = (1 + fixed_rate_annual) ** (1 / seconds_per_year) - 1
fixed_rate_per_day = (1 + fixed_rate_annual) ** (1 / 365) - 1

st.write(f"**Fixed rate per second:** {fixed_rate_per_sec:.12f}  •  **per day:** {fixed_rate_per_day:.8f}")

# =========================
# 3) Collateral & borrow sizing
# =========================
st.subheader("2) Collateral & Borrow Capacity")

st.write("We’ll either fetch collateral factors from the Comet contract (if you provide an RPC URL) or you can enter them manually.")

rpc_url = st.text_input("Optional Ethereum RPC URL (Infura/Alchemy). Leave blank to enter factors manually.", value=os.environ.get("RPC_URL", st.secrets.get("RPC_URL", "")))

use_web3 = False
borrow_cf = None
liq_cf = None
liq_penalty = None

if rpc_url:
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            st.warning("RPC not connected; falling back to manual input.")
        else:
            use_web3 = True
            comet = w3.eth.contract(address=w3.to_checksum_address(COMET_USDC_MAINNET), abi=COMET_MIN_ABI)
            info = comet.functions.getAssetInfoByAddress(w3.to_checksum_address(WETH_MAINNET)).call()
            # unpack factors (scaled by 1e18)
            borrow_cf = info[4] / 1e18
            liq_cf    = info[5] / 1e18
            liq_factor= info[6] / 1e18
            liq_penalty = 1 - liq_factor  # penalty is (1 - liquidationFactor)
            st.success("Pulled collateral factors via Web3.")
    except Exception as e:
        st.warning(f"Web3 error: {e}. Falling back to manual input.")

if not use_web3:
    st.info("Enter collateral parameters manually (these vary per market/asset; examples only).")
    borrow_cf    = st.number_input("Borrow Collateral Factor (decimal, e.g. 0.75)", 0.0, 1.0, 0.75, 0.01)
    liq_cf       = st.number_input("Liquidate Collateral Factor (decimal, e.g. 0.85)", 0.0, 1.0, 0.85, 0.01)
    liq_penalty  = st.number_input("Liquidation penalty (decimal, e.g. 0.07 = 7%)", 0.0, 0.5, 0.07, 0.005)

col = st.columns(3)
col[0].metric("Borrow CF", f"{borrow_cf*100:.2f}%")
col[1].metric("Liquidate CF", f"{liq_cf*100:.2f}%")
col[2].metric("Liquidation penalty", f"{liq_penalty*100:.2f}%")

st.write("**Inputs for your position:**")
eth_collateral = st.number_input("ETH collateral amount", min_value=0.0, value=10.0, step=0.1)
eth_price      = st.number_input("ETH price (USD)", min_value=0.0, value=3000.0, step=10.0)

collateral_usd = eth_collateral * eth_price
max_borrow_usd = collateral_usd * borrow_cf

st.write(f"- Collateral value: **${collateral_usd:,.2f}**  •  Max borrow (USDC): **${max_borrow_usd:,.2f}**")

borrow_usd = st.number_input("Borrow amount (USDC)", min_value=0.0, max_value=float(max_borrow_usd), value=round(max_borrow_usd*0.9, 2), step=100.0)
st.caption("Tip: start below max to reduce liquidation risk.")

# =========================
# 4) Build floating & fixed legs (daily)
# =========================
st.subheader("3) Swap Simulation (Daily)")

sim_days = st.slider("Simulation horizon (days)", 30, min(lookback_days, 365), min(lookback_days, 180))
hist = df.tail(sim_days).copy()

# Convert annual APRs in history to daily rates
hist["borrow_rate_daily"] = (1 + hist["borrowApr_annual"]) ** (1/365) - 1
hist["supply_rate_daily"] = (1 + hist["supplyApr_annual"]) ** (1/365) - 1

# Fixed & floating cashflows (payer-fixed vs receiver-floating from the borrower's POV):
# - Debt accrues daily at floating daily rate on outstanding borrow
# - Fixed leg pays fixed_rate_per_day * borrow_usd (simplified plain-vanilla)
outstanding = borrow_usd
rows = []
cum_net = 0.0

for i, row in hist.iterrows():
    day = row["date"].date()
    rf = float(row["borrow_rate_daily"])   # floating daily borrow rate
    fixed_pay = borrow_usd * fixed_rate_per_day
    float_pay = outstanding * rf  # interest on current outstanding

    net = fixed_pay - float_pay   # payer-fixed, receiver-floating
    cum_net += net

    # Update debt (interest accrues)
    outstanding = outstanding * (1 + rf)

    # Health / liquidation check
    # Liquidation if debt > liq_cf * collateral_usd
    healthy_limit = liq_cf * collateral_usd
    liquidated = outstanding > healthy_limit

    rows.append({
        "date": day,
        "borrow_apr_annual": float(row["borrowApr_annual"]),
        "float_rate_daily": rf,
        "fixed_rate_daily": fixed_rate_per_day,
        "float_interest": float_pay,
        "fixed_payment": fixed_pay,
        "net_cashflow": net,
        "cum_net_cashflow": cum_net,
        "outstanding_debt": outstanding,
        "liq_threshold": healthy_limit,
        "ltv": outstanding / collateral_usd if collateral_usd > 0 else math.inf,
        "breach_liquidation": liquidated
    })

sim = pd.DataFrame(rows)

st.write("**Cashflows & risk over time (last rows):**")
st.dataframe(sim.tail(10), use_container_width=True)

st.write("**Charts**")
st.line_chart(sim.set_index("date")[["fixed_payment", "float_interest"]])
st.line_chart(sim.set_index("date")[["cum_net_cashflow"]])
st.line_chart(sim.set_index("date")[["outstanding_debt", "liq_threshold"]])

# Summary
ltv_now = sim["ltv"].iloc[-1]
any_liq = sim["breach_liquidation"].any()
col1, col2, col3 = st.columns(3)
col1.metric("Current LTV", f"{ltv_now*100:.2f}%")
col2.metric("Liquidation breached?", "Yes" if any_liq else "No")
col3.metric("Final outstanding (USDC)", f"${sim['outstanding_debt'].iloc[-1]:,.2f}")

st.info(
    "Interpretation:\n"
    "- **Fixed vs Floating**: If `cum_net_cashflow` > 0, paying fixed was cheaper than floating over the window (good for borrower paying fixed).\n"
    "- **Liquidation**: If `outstanding_debt` crosses `liq_threshold`, the position would be liquidated under those conditions.\n"
)

# =========================
# 5) Download results
# =========================
st.download_button(
    "Download simulation CSV",
    data=sim.to_csv(index=False),
    file_name="compound_v3_swap_simulation.csv",
    mime="text/csv"
)
