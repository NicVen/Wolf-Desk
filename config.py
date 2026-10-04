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
  "stocks": {
    "label": "Stocks", "signals": "signals_stocks.json",
    "universe": {
      "NVIDIA":    ("NVDA", "AI/Semi", "stocks"),
      "AMD":       ("AMD",  "AI/Semi", "stocks"),
      "Broadcom":  ("AVGO", "AI/Semi", "stocks"),
      "Microsoft": ("MSFT", "Megacap", "stocks"),
      "Apple":     ("AAPL", "Megacap", "stocks"),
      "Meta":      ("META", "Megacap", "stocks"),
      "Amazon":    ("AMZN", "Megacap", "stocks"),
      "Alphabet":  ("GOOGL","Megacap", "stocks"),
      "Tesla":     ("TSLA", "Growth", "stocks"),
      "Palantir":  ("PLTR", "Growth", "stocks"),
    }},
  "crypto": {
    "label": "Crypto", "signals": "signals_crypto.json",
    "universe": {
      "Bitcoin":       ("BTC-USD",   "L1",       "crypto"),
      "Ethereum":      ("ETH-USD",   "L1",       "crypto"),
      "BNB":           ("BNB-USD",   "L1",       "crypto"),
      "Solana":        ("SOL-USD",   "L1",       "crypto"),
      "XRP":           ("XRP-USD",   "Payments", "crypto"),
      "Cardano":       ("ADA-USD",   "L1",       "crypto"),
      "Dogecoin":      ("DOGE-USD",  "Meme",     "crypto"),
      "TRON":          ("TRX-USD",   "L1",       "crypto"),
      "Avalanche":     ("AVAX-USD",  "L1",       "crypto"),
      "Chainlink":     ("LINK-USD",  "Oracle",   "crypto"),
      "Polkadot":      ("DOT-USD",   "L1",       "crypto"),
      "Polygon":       ("POL-USD",   "L2",       "crypto"),
      "Shiba Inu":     ("SHIB-USD",  "Meme",     "crypto"),
      "Litecoin":      ("LTC-USD",   "Payments", "crypto"),
      "Bitcoin Cash":  ("BCH-USD",   "Payments", "crypto"),
      "Uniswap":       ("UNI-USD",   "DeFi",     "crypto"),
      "NEAR":          ("NEAR-USD",  "L1",       "crypto"),
      "Aptos":         ("APT-USD",   "L1",       "crypto"),
      "Internet Computer": ("ICP-USD","L1",      "crypto"),
      "Ethereum Classic":  ("ETC-USD","L1",      "crypto"),
      "Stellar":       ("XLM-USD",   "Payments", "crypto"),
      "Cosmos":        ("ATOM-USD",  "L1",       "crypto"),
      "Filecoin":      ("FIL-USD",   "Storage",  "crypto"),
      "Hedera":        ("HBAR-USD",  "L1",       "crypto"),
      "Arbitrum":      ("ARB-USD",   "L2",       "crypto"),
      "Optimism":      ("OP-USD",    "L2",       "crypto"),
      "VeChain":       ("VET-USD",   "L1",       "crypto"),
      "Immutable":     ("IMX10603-USD", "Gaming", "crypto"),
      "Injective":     ("INJ-USD",   "DeFi",     "crypto"),
      "The Graph":     ("GRT6719-USD",  "Infra",  "crypto"),
      "Aave":          ("AAVE-USD",  "DeFi",     "crypto"),
      "Maker":         ("MKR-USD",   "DeFi",     "crypto"),
      "Render":        ("RENDER-USD",   "AI/DePIN", "crypto"),
      "Algorand":      ("ALGO-USD",  "L1",       "crypto"),
      "The Sandbox":   ("SAND-USD",  "Metaverse","crypto"),
      "Decentraland":  ("MANA-USD",  "Metaverse","crypto"),
      "Axie Infinity": ("AXS-USD",   "Gaming",   "crypto"),
      "Theta":         ("THETA-USD", "Media",    "crypto"),
      "MultiversX":    ("EGLD-USD",  "L1",       "crypto"),
      "Flow":          ("FLOW-USD",  "L1",       "crypto"),
      "Tezos":         ("XTZ-USD",   "L1",       "crypto"),
      "Chiliz":        ("CHZ-USD",   "Fan",      "crypto"),
      "Quant":         ("QNT-USD",   "Infra",    "crypto"),
      "Kaspa":         ("KAS-USD",   "L1",       "crypto"),
      "Sui":           ("SUI20947-USD", "L1",     "crypto"),
      "Sei":           ("SEI-USD",   "L1",       "crypto"),
      "Celestia":      ("TIA-USD",   "Infra",    "crypto"),
      "Pepe":          ("PEPE24478-USD","Meme",   "crypto"),
      "dogwifhat":     ("WIF-USD",   "Meme",     "crypto"),
      "Bonk":          ("BONK-USD",  "Meme",     "crypto"),
      "Floki":         ("FLOKI-USD", "Meme",     "crypto"),
      "Jupiter":       ("JUP-USD",   "DeFi",     "crypto"),
      "THORChain":     ("RUNE-USD",  "DeFi",     "crypto"),
      "Curve":         ("CRV-USD",   "DeFi",     "crypto"),
      "Lido DAO":      ("LDO-USD",   "DeFi",     "crypto"),
      "Stacks":        ("STX4847-USD",  "BTC L2", "crypto"),
    }},
}
