import requests
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

# -------------------------------
# Step 1: Fetch data from The Graph
# -------------------------------
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"

headers = {"Content-Type": "application/json"}

query = """
{
  markets {
    id
  }
  dailyMarketAccountings(first: 1000, where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" }) {
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
    "borrowApr": [entry["accounting"]["borrowApr"] for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [entry["accounting"]["supplyApr"] for entry in data["data"]["dailyMarketAccountings"]],
})

# Convert numeric values
df["borrowApr"] = df["borrowApr"].astype(float)
df["supplyApr"] = df["supplyApr"].astype(float)
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")

# -------------------------------
# Step 2: Streamlit UI
# -------------------------------
st.title("💹 Compound Swap Simulator")
st.markdown("Simulate a **fixed vs floating interest rate swap** using Compound APR data.")

# Show recent APR data
st.subheader("Latest APRs")
st.dataframe(df.tail(10))

# -------------------------------
# Step 3: User Inputs
# -------------------------------
st.subheader("Swap Simulation")
amount = st.number_input("Enter amount ($):", min_value=100, step=100, value=1000)
duration_days = st.number_input("Enter duration (days):", min_value=1, max_value=365, value=30)

# -------------------------------
# Step 4: Swap Calculation
# -------------------------------
def calculate_swap(amount, duration_days, df):
    # Fixed = average APR (borrow side) over history
    fixed_rate = df["borrowApr"].mean()

    # Floating = simulate using recent data
    recent = df.tail(duration_days) if duration_days < len(df) else df
    floating_growth = np.prod([1 + r/100/365 for r in recent["borrowApr"]])

    floating_cost = amount * (floating_growth - 1)
    fixed_cost = amount * (fixed_rate/100) * (duration_days/365)

    return fixed_rate, fixed_cost, floating_cost

# Run calculation when button pressed
if st.button("Simulate Swap"):
    fixed_rate, fixed_cost, floating_cost = calculate_swap(amount, duration_days, df)

    st.write(f"**Fixed Rate (annual): {fixed_rate:.2f}%**")
    st.write(f"**Cost at Fixed Rate: ${fixed_cost:.2f}**")
    st.write(f"**Cost at Floating Rate: ${floating_cost:.2f}**")

    if fixed_cost < floating_cost:
        st.success("✅ Fixed rate is cheaper in this scenario.")
    else:
        st.warning("⚠️ Floating rate is cheaper in this scenario.")

    # Plot APR history
    st.subheader("APR Trend (last 90 days)")
    fig, ax = plt.subplots()
    ax.plot(df["timestamp"].tail(90), df["borrowApr"].tail(90), label="Floating APR")
    ax.axhline(y=fixed_rate, color='r', linestyle='--', label="Fixed Rate")
    ax.set_ylabel("APR (%)")
    ax.legend()
    st.pyplot(fig)
