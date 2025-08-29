import requests
import pandas as pd
import streamlit as st

# Set the API endpoint and headers
api_key = "3b6cc500833cb7c07f3eb2e97bc88709"
url = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/5nwMCSHaTqG3Kd2gHznbTXEnZ9QNWsssQfbHhDqQSQFp"

headers = {
    "Content-Type": "application/json"
}

# Define the GraphQL query
query = """
{
  markets{
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

# Make the request
response = requests.post(url, json={"query": query}, headers=headers)
data = response.json()

# Create a Pandas DataFrame
df = pd.DataFrame({
    "timestamp": [entry["timestamp"] for entry in data["data"]["dailyMarketAccountings"]],
    "borrowApr": [entry["accounting"]["borrowApr"] for entry in data["data"]["dailyMarketAccountings"]],
    "supplyApr": [entry["accounting"]["supplyApr"] for entry in data["data"]["dailyMarketAccountings"]]
})

# Streamlit UI
st.title("Compound V3 Market Data")
st.write("This is a simple tool to view borrow and supply APRs.")
st.dataframe(df)
