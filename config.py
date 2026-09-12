"""THE WOLF PROJECT — config: multi-asset universes + scoring weights.

Each universe item: name -> (yahoo_ticker, display_category, coverage_key)
coverage_key matches a boolean column in data/brokers.json.
"""

# Scoring weights (max points). Total = 100.
W_CATALYST = 25   # upcoming event / news catalyst   (manual signals)
W_TREND    = 25   # price vs MAs + momentum          (auto, prices)
W_POSITION = 20   # positioning / sentiment extreme  (manual)
W_SUPPLY   = 20   # supply-demand / fundamentals     (manual)
W_VOLFIT   = 10   # tradeable volatility band        (auto)

DATA_DIR = "data"

ASSET_CLASSES = {
  "commodities": {
    "label": "Commodities", "signals": "signals_commodities.json",
    "universe": {
      "Gold":       ("GC=F", "Metals", "metals"),
      "Silver":     ("SI=F", "Metals", "metals"),
      "Copper":     ("HG=F", "Metals", "metals"),
      "Platinum":   ("PL=F", "Metals", "metals"),
      "Palladium":  ("PA=F", "Metals", "metals"),
      "WTI Crude":  ("CL=F", "Energy", "energy"),
      "Brent":      ("BZ=F", "Energy", "energy"),
      "Natural Gas":("NG=F", "Energy", "energy"),
      "Wheat":      ("ZW=F", "Ags", "ags"),
      "Corn":       ("ZC=F", "Ags", "ags"),
      "Soybeans":   ("ZS=F", "Ags", "ags"),
      "Coffee":     ("KC=F", "Ags", "ags"),
      "Sugar":      ("SB=F", "Ags", "ags"),
      "Cocoa":      ("CC=F", "Ags", "ags"),
    }},
  "fx": {
    "label": "FX", "signals": "signals_fx.json",
    "universe": {
      "EUR/USD": ("EURUSD=X", "Major", "fx"),
      "GBP/USD": ("GBPUSD=X", "Major", "fx"),
      "USD/JPY": ("USDJPY=X", "Major", "fx"),
      "USD/CHF": ("USDCHF=X", "Major", "fx"),
      "USD/CAD": ("USDCAD=X", "Major", "fx"),
      "AUD/USD": ("AUDUSD=X", "Major", "fx"),
      "NZD/USD": ("NZDUSD=X", "Major", "fx"),
      "EUR/JPY": ("EURJPY=X", "JPY cross", "fx"),
      "GBP/JPY": ("GBPJPY=X", "JPY cross", "fx"),
      "EUR/GBP": ("EURGBP=X", "Cross", "fx"),
    }},
  "crypto": {
    # 24/7 market — the only desk that trades on weekends (see wolf_post.py).
    "label": "Crypto", "signals": "signals_crypto.json",
    "universe": {
      "BTC/USD":  ("BTC-USD",  "Major",   "crypto"),
      "ETH/USD":  ("ETH-USD",  "Major",   "crypto"),
      "SOL/USD":  ("SOL-USD",  "Altcoin", "crypto"),
      "XRP/USD":  ("XRP-USD",  "Altcoin", "crypto"),
      "BNB/USD":  ("BNB-USD",  "Altcoin", "crypto"),
      "ADA/USD":  ("ADA-USD",  "Altcoin", "crypto"),
      "DOGE/USD": ("DOGE-USD", "Altcoin", "crypto"),
      "AVAX/USD": ("AVAX-USD", "Altcoin", "crypto"),
      "LINK/USD": ("LINK-USD", "Altcoin", "crypto"),
      "LTC/USD":  ("LTC-USD",  "Altcoin", "crypto"),
    }},
  "indices": {
    "label": "Indices", "signals": "signals_indices.json",
    "universe": {
      "S&P 500":    ("^GSPC",    "US", "indices"),
      "Nasdaq 100": ("^NDX",     "US", "indices"),
      "Dow Jones":  ("^DJI",     "US", "indices"),
      "Russell 2000":("^RUT",    "US", "indices"),
      "DAX":        ("^GDAXI",   "EU", "indices"),
      "FTSE 100":   ("^FTSE",    "EU", "indices"),
      "Euro Stoxx 50":("^STOXX50E","EU","indices"),
      "Nikkei 225": ("^N225",    "Asia", "indices"),
      "Hang Seng":  ("^HSI",     "Asia", "indices"),
      "ASX 200":    ("^AXJO",    "Asia", "indices"),
    }},
}
