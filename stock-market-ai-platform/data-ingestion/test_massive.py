from massive_client import MassiveClient

client = MassiveClient()

print("Client created")

data = client.get_daily_prices(
    "AAPL",
    "2021-01-01",
    "2026-01-01"
)

print("API call complete")
print(type(data))
print(data.head())
