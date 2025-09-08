import streamlit as st
import requests
import pandas as pd
import numpy as np

# --------------------------
# 1. Page setup
# --------------------------
st.title("Compound Fixed Rate Swap Simulator — No web3")
st.write("This version fetches everything from The Graph & Chainlink APIs, no web3 required.")

# --------------------------
# 2. Fetch asset factors from The Graph
# --------------------------
@st.cache_data(ttl=600)
def get_asset_factors():
    url = "https://gateway.thegraph.com/api/YOUR_KEY/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"
    headers = {"Content-Type": "application/json"}
    query = """
    {
      assets(where: { market: "0xc3d688B66703497DAA19211EEdff47f25384cdc3" }) {
        id
        borrowCollateralFactor
        liquidateCollateralFactor
        liquidationFactor
      }
    }
    """
    r = requests.post(url, json={"query": query}, headers=headers)
    r.raise_for_status()
    data = r.json()["data"]["assets"][0]
    return {
        "borrow_cf": float(data["borrowCollateralFactor"]) / 1e18,
        "liquidate_cf": float(data["liquidateCollateralFactor"]) / 1e18,
        "liquidation_factor": float(data["liquidationFactor"]) / 1e18,
    }

factors = get_asset_factors()
st.write("📊 Collateral Factors")
st.json(factors)

# --------------------------
# 3. Fetch ETH/USDC price from Chainlink
# --------------------------
@st.cache_data(ttl=300)
def get_eth_price_usdc():
    # ETH/USD feed
    ethusd = requests.get(
        "https://api.redstone.finance/prices?symbol=ETH&provider=chainlink&limit=1"
    ).json()[0]["value"]

    # USDC/USD feed
    usdcusd = requests.get(
        "https://api.redstone.finance/prices?symbol=USDC&provider=chainlink&limit=1"
    ).json()[0]["value"]

    return ethusd / usdcusd

try:
    eth_price_usdc = get_eth_price_usdc()
    st.success(f"💰 Current ETH Price (USDC): {eth_price_usdc:,.2f}")
except Exception as e:
    st.error(f"Failed to fetch ETH/USDC price: {e}")
    eth_price_usdc = st.number_input("Enter ETH Price manually (USDC)", min_value=500.0, value=2000.0, step=10.0)
