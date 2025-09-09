import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Simulator — Daily Floating Rates")

# --------------------------
# 2. Hardcoded collateral factors
# --------------------------
BORROW_CF = 0.825
LIQUIDATE_CF = 0.88
LIQUIDATION_PENALTY = 0.07

# --------------------------
# 3. Fetch ETH price via Infura
# --------------------------
INFURA_URL = "https://mainnet.infura.io/v3/your_infura_project_id"

def get_eth_price_usd():
    try:
        url = "https://api.coinbase.com/v2/prices/ETH-USD/spot"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return float(r.json()["data"]["amount"])
    except Exception:
        return None

eth_price = get_eth_price_usd()
if eth_price:
    st.success(f"💰 Current ETH Price (USD): ${eth_price:,.2f}")
else:
    st.error("Failed to fetch ETH price.")
    eth_price = st.number_input("Enter ETH Price manually (USD)", min_value=500.0, value=2000.0, step=10.0)

# --------------------------
# 4. Fetch 1000 APR points
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

# Construct dataframe
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

# --------------------------
# 5. Show 10 most recent APRs
# --------------------------
df_last10 = df.tail(10).sort_values("timestamp", ascending=False)
st.subheader("📊 Most Recent 10 APRs")
st.dataframe(df_last10[["timestamp", "borrowApr", "supplyApr"]].reset_index(drop=True))

st.subheader("📈 Historical APR Chart (Full 1000 Days)")
st.line_chart(df.set_index("timestamp")[ ["borrowApr", "supplyApr"] ])

# --------------------------
# 6. Swap Simulator Inputs
# --------------------------
st.subheader("💡 Swap Simulator Settings")
eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=1.0, value=10.0, step=0.5)
simulation_days = st.slider("Simulation Period (Days)", 1, 1000, 30)

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
# 8. Backtest-derived Fixed Rate Selection
# --------------------------
def backtest_for_fixed_rate(df, max_borrow_usd, liquidation_threshold, horizon):
    safety_buffer = max_borrow_usd - liquidation_threshold

    # Candidate floating rates (borrow APRs)
    series = df.tail(horizon)["borrowApr"].values

    # Daily floating rates
    floating_daily = (1 + series) ** (1/365) - 1

    # Binary search fixed rate
    lo, hi = 0.0, 0.5  # 0% to 50%
    best_rate = lo

    for _ in range(40):  # 40 iterations ~ 1e-12 precision
        mid = (lo + hi) / 2
        fixed_daily = (1 + mid) ** (1/365) - 1

        cum_net = 0.0
        safe = True

        for r in floating_daily:
            floating_payment = max_borrow_usd * r
            fixed_payment = max_borrow_usd * fixed_daily
            net = fixed_payment - floating_payment
            cum_net += net

            if cum_net < -safety_buffer:
                safe = False
                break

        if safe:
            best_rate = mid
            lo = mid
        else:
            hi = mid

    return best_rate

fixed_rate_annual = backtest_for_fixed_rate(df, max_borrow_usd, liquidation_threshold, simulation_days)
fixed_rate_daily = (1 + fixed_rate_annual) ** (1/365) - 1

st.subheader("🔮 Fixed Rate Determination")
st.write(f"📈 Fixed Rate (annual): {fixed_rate_annual*100:.2f}%")
st.write(f"➡️ Daily Fixed Rate: {fixed_rate_daily*100:.4f}%")

# --------------------------
# 9. Daily Cashflow Simulation
# --------------------------
recent_floating = df.tail(simulation_days)["borrowApr"].values
floating_rates_daily = (1 + recent_floating) ** (1/365) - 1

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
        "Floating APR (annual %)": f"{recent_floating[i]*100:.4f}",
        "Floating Payment (USD)": floating_payment,
        "Fixed Payment (USD)": fixed_payment,
        "Net Cashflow (USD)": net,
        "Cumulative Net Cashflow (USD)": cumulative_net
    })

results_df = pd.DataFrame(results)
st.subheader("📑 Daily Cashflows & Cumulative Net")
st.dataframe(results_df)
st.line_chart(results_df.set_index("Day")[ ["Floating Payment (USD)", "Fixed Payment (USD)"] ])

# --------------------------
# 10. Final Liquidation Check
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")
if liquidated_day:
    st.error(f"❌ Liquidation triggered on Day {liquidated_day}!")
else:
    st.success("✅ No liquidation during the simulation horizon.")
