"""Central configuration.  To add a new instrument (stock / crypto later),
add one entry to ASSETS - nothing else in the app is hard-coded to these four."""
import os
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

IST = ZoneInfo("Asia/Kolkata")

NUBRA_ENV = os.getenv("NUBRA_ENV", "PROD").upper()
USE_MOCK = os.getenv("USE_MOCK", "0") == "1"
DB_PATH = os.getenv("DB_PATH", "data/cache.db")

# exchange-native integer -> rupees.  NSE and MCX both return paise per the SDK docs.
PRICE_DIVISOR = 100

# `underlying` is the symbol passed to option_chain().  Verify GOLD vs GOLDM etc. against
# the `asset` column of instruments.get_instruments_dataframe(exchange="MCX").
ASSETS = {
    "NIFTY":     dict(label="Nifty 50",   exchange="NSE", kind="index",     underlying="NIFTY",     step=50),
    "BANKNIFTY": dict(label="Bank Nifty", exchange="NSE", kind="index",     underlying="BANKNIFTY", step=100),
    "GOLD":      dict(label="Gold",       exchange="MCX", kind="commodity", underlying="GOLD",      step=100),
    "CRUDEOIL":  dict(label="Crude Oil",  exchange="MCX", kind="commodity", underlying="CRUDEOIL",  step=50),
}

# local session times (IST)
SESSIONS = {
    "NSE": (time(9, 15), time(15, 30)),
    "MCX": (time(9, 0), time(23, 30)),
}

MAX_DEPTH = 20            # strikes from ATM towards OTM
HIST_MIN_INTERVAL = 1.05  # seconds between historical calls  (limit: 60/min)
LIVE_TTL = 3              # seconds - live chain cache so many browser tabs don't hammer the API
