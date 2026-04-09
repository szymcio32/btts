"""Constants for btts-bot: API URLs, enums, and shared values."""

# Polymarket CLOB API
CLOB_HOST: str = "https://clob.polymarket.com"
CHAIN_ID: int = 137  # POLYGON

# Polymarket Data API (positions, portfolio data)
DATA_API_HOST: str = "https://data-api.polymarket.com"

# Signature type for Polymarket proxy wallets (POLY_GNOSIS_SAFE = 2)
POLY_GNOSIS_SAFE: int = 2

# Order sides (used in OrderArgs.side)
BUY_SIDE: str = "BUY"
SELL_SIDE: str = "SELL"
