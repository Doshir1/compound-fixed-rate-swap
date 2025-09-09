import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# App configuration
# --------------------------
st.set_page_config(page_title="Compound Fixed Rate Swap", layout="wide")
st.title("Compound Fixed Rate Swap Simulator — Daily Floating Rates")
st.write(
    "Fetches historical APRs from The Graph, uses an on‑site price feed, runs a backtest to pick a fixed rate,"
    " simulates daily cashflows, and checks liquidation risk."
)

# --------------------------
# Hardcoded collateral factors (per your instruction)
# --------------------------
BORROW_CF = 0.825
LIQUIDATE_CF = 0.88
LIQ_PENALTY = 0.07

# --------------------------
# ETH price (no web3) — using Coinbase public spot API (works reliably in Streamlit Cloud)
# --------------------------
@st.cache_data(ttl=300)
def get_eth_price_usd():
    url = "https://api.coinbase.com/v2/prices/ETH-USD/spot"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return float(r.json()["data"]["amount"])

try:
    eth_price = get_eth_price_usd()
    st.success(f"💰 Current ETH Price (USD): ${eth_price:,.2f}")
except Exception as e:
    st.error("Failed to fetch ETH price — please enter manually.")
    eth_price = st.number_input("Enter ETH Price manually (USD)", min_value=100.0, value=2000.0, step=1.0)

# --------------------------
# Fetch 1000 APR points from The Graph
# --------------------------
API_KEY = "3b6cc500833cb7c07f3eb2e97bc88709"
GRAPH_URL = f"https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"

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

r = requests.post(GRAPH_URL, json={"query": query})
r.raise_for_status()
data = r.json()

# defensive check
if data.get("data") is None or data["data"].get("dailyMarketAccountings") is None:
    st.error("Failed to fetch APR time series from The Graph — check API key / connectivity.")
    st.stop()

rows = data["data"]["dailyMarketAccountings"]

df = pd.DataFrame({
    "timestamp": [row["timestamp"] for row in rows],
    "borrowApr": [float(row["accounting"]["borrowApr"]) for row in rows],
    "supplyApr": [float(row["accounting"]["supplyApr"]) for row in rows]
})

df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
# ensure chronological order (oldest -> newest)
df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)

# convert to decimals if The Graph returned percentages
if df["borrowApr"].mean() > 1:
    df["borrowApr"] = df["borrowApr"] / 100.0
    df["supplyApr"] = df["supplyApr"] / 100.0

# --------------------------
# APR table: 10 most recent rows (newest -> oldest)
# --------------------------
st.subheader("📊 Most Recent 10 APRs")
df_last10 = df.sort_values("timestamp", ascending=False).head(10).reset_index(drop=True)
# format as percentage for readability
df_last10_display = df_last10.copy()
df_last10_display["borrowApr"] = (df_last10_display["borrowApr"] * 100).map("{:.4f}%".format)
df_last10_display["supplyApr"] = (df_last10_display["supplyApr"] * 100).map("{:.4f}%".format)
st.dataframe(df_last10_display[["timestamp", "borrowApr", "supplyApr"]])

# full historical chart (1000 points)
st.subheader("📈 Historical APR Chart (Full history)")
st.line_chart(df.set_index("timestamp")[ ["borrowApr", "supplyApr"] ])

# --------------------------
# Simulator inputs
# --------------------------
st.subheader("💡 Swap Simulator Settings")
eth_collateral = st.number_input("Deposit ETH as Collateral", min_value=0.1, value=10.0, step=0.1)
# allow up to 1000 days per your request
simulation_period = st.slider("Simulation Period (Days)", 1, min(1000, len(df)), value=30)

# --------------------------
# Borrow capacity and liquidation
# --------------------------
collateral_value_usd = eth_collateral * eth_price
max_borrow_usd = collateral_value_usd * BORROW_CF
liquidation_threshold = collateral_value_usd * LIQUIDATE_CF
safety_buffer = max_borrow_usd - liquidation_threshold  # typically negative

st.write(f"🔒 Collateral Value: ${collateral_value_usd:,.2f}")
st.write(f"📉 Max Borrow Capacity: ${max_borrow_usd:,.2f}")
st.write(f"⚠️ Liquidation Threshold: ${liquidation_threshold:,.2f}")
st.write(f"🛡️ Safety buffer (borrow - liquidation): ${safety_buffer:,.2f}")

# --------------------------
# Helper: check if a candidate fixed rate (annual) is SAFE for a given series
# Returns True if cumulative net cashflow never goes below safety_buffer
# --------------------------

def is_fixed_rate_safe_for_series(fixed_rate_annual, series_aprs, max_borrow_amount, safety_buffer_val):
    fixed_daily = (1.0 + fixed_rate_annual) ** (1.0 / 365.0) - 1.0
    cum_net = 0.0
    for apr in series_aprs:
        floating_daily = (1.0 + apr) ** (1.0 / 365.0) - 1.0
        net = max_borrow_amount * (fixed_daily - floating_daily)
        cum_net += net
        if cum_net < safety_buffer_val:
            return False
    return True

# --------------------------
# Compute minimal safe fixed rate for a single window using binary search
# We find the smallest annual fixed rate such that the cumulative net >= safety_buffer
# --------------------------

def minimal_safe_rate_for_window(series_aprs, max_borrow_amount, safety_buffer_val):
    # initial bounds (annual rates)
    lo = 0.0
    # hi: start from a value guaranteed to be safe; use historical max + margin
    hi = max(1.0, float(np.max(series_aprs)) + 1.0)

    # ensure hi is safe; if not, increase until safe (rare)
    attempts = 0
    while not is_fixed_rate_safe_for_series(hi, series_aprs, max_borrow_amount, safety_buffer_val) and attempts < 60:
        hi *= 2.0
        attempts += 1

    # binary search for minimal safe rate
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if is_fixed_rate_safe_for_series(mid, series_aprs, max_borrow_amount, safety_buffer_val):
            hi = mid
        else:
            lo = mid
    return hi

# --------------------------
# Backtest across windows: user period -> period, 2*period, 3*period, ... up to len(df) (capped at 1000)
# For each window we compute the minimal safe fixed rate; final fixed rate = max(of those minima)
# This produces the smallest fixed rate that is safe across all tested backtest windows
# --------------------------

st.subheader("🔮 Backtest-derived Fixed Rate")
period = simulation_period
max_len = min(1000, len(df))
window_sizes = list(range(period, max_len + 1, period))
if window_sizes[-1] != max_len:
    # ensure we include the full-history window as well
    window_sizes.append(max_len)

per_window_minima = []
for w in window_sizes:
    series = df["borrowApr"].tail(w).values  # last w samples (chronological order)
    r_min = minimal_safe_rate_for_window(series, max_borrow_usd, safety_buffer)
    per_window_minima.append(r_min)

# final fixed rate = maximum of the minimal safe rates across windows
fixed_rate_annual = float(np.max(per_window_minima))
fixed_rate_daily = (1.0 + fixed_rate_annual) ** (1.0 / 365.0) - 1.0

st.write(f"📈 Fixed Rate (annual) determined by backtest: {fixed_rate_annual*100:.6f}%")
st.write(f"➡️ Fixed Rate (daily accrual): {fixed_rate_daily*100:.6f}%")

# --------------------------
# Use the most recent `simulation_period` borrow APRs as floating rates in the simulator
# --------------------------
recent_aprs = df["borrowApr"].tail(simulation_period).values
# ensure chronological order oldest -> newest for the simulation
if len(recent_aprs) >= 2 and df["timestamp"].iloc[-simulation_period] > df["timestamp"].iloc[-1]:
    recent_aprs = recent_aprs[::-1]

floating_rates_daily = (1.0 + recent_aprs) ** (1.0 / 365.0) - 1.0

# --------------------------
# Daily cashflow simulation using the chosen fixed rate
# --------------------------
st.subheader("📑 Daily Cashflows & Cumulative Net")
results = []
cum_net = 0.0
liquidated_day = None
for i in range(simulation_period):
    floating_payment = max_borrow_usd * floating_rates_daily[i]
    fixed_payment = max_borrow_usd * fixed_rate_daily
    net = fixed_payment - floating_payment
    cum_net += net

    effective_debt = max_borrow_usd - cum_net
    if effective_debt > liquidation_threshold and liquidated_day is None:
        liquidated_day = i + 1
        st.warning(f"⚠️ Absorb() called on Day {liquidated_day} due to LCF breach!")

    results.append({
        "Day": i + 1,
        "Floating APR (annual %)": f"{recent_aprs[i]*100:.4f}",
        "Floating Payment (USD)": floating_payment,
        "Fixed Payment (USD)": fixed_payment,
        "Net Cashflow (USD)": net,
        "Cumulative Net Cashflow (USD)": cum_net
    })

results_df = pd.DataFrame(results)
st.dataframe(results_df)
st.line_chart(results_df.set_index("Day")[ ["Floating Payment (USD)", "Fixed Payment (USD)"] ])

# --------------------------
# Final liquidation summary
# --------------------------
st.subheader("⚠️ Liquidation Risk Check")
if liquidated_day:
    st.error(f"❌ Liquidation triggered on Day {liquidated_day}!")
else:
    st.success("✅ No liquidation during the simulation horizon.")
