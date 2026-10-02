# Derivatives Analyzer

Option chain + Greeks analysis (live and historical) for **Nifty, Bank Nifty, Gold, Crude Oil**,
built on the [Nubra Python SDK](https://nubra.io) (`nubra-sdk` 0.5.x).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # fill PHONE_NO and MPIN

python run.py            # then open http://127.0.0.1:8000
```

* **First run:** start from a terminal - the SDK asks for the OTP sent to your phone there.
* **No credentials yet?** `USE_MOCK=1 python run.py` runs the full UI on synthetic Black-Scholes data.
* `NUBRA_ENV=UAT` for sandbox. `ref_id`s differ between UAT and PROD, so don't mix them.
* Tests: `pytest -q` (greeks maths + API in mock mode).

## Pages

**Option Chain** - CE | Strike | PE with OI (bars), OI change, volume, IV, delta, theta, vega, LTP.
Live (auto-refresh 5 s) or Historical (pick a date and time, then Load; use +1m/+3m/+5m/+10m to move forward).

**Greeks Analysis** - three tables, rows CE / PE, columns Delta / Theta / Vega:

| Table | Underlying price used | Greeks as of |
|---|---|---|
| 1. Opening | opening price -> ATM at open | first candle of the session |
| 2. Current (or Selected time) | current price -> ATM now | now / chosen time |
| 3. Change | table 2 - table 1 | |

"Sum ATM -> OTM": CE = ATM + the next `depth` strikes above; PE = ATM + the next `depth` strikes below.
`depth` is selectable (1-20). Plus a chart of the change since open for the day.

## How it works

```
static/            plain HTML/JS UI (Chart.js from cdnjs)
app/main.py        FastAPI: /api/assets /expiries /chain/live /greeks/live /historical
app/nubra_client.py  all Nubra SDK calls, paise->rupees, throttle (60 hist req/min), disk cache
app/history.py     rebuilds option-chain snapshots from historical_data(); opening baseline
app/greeks.py      pure maths for the 3 tables (unit-tested)
app/mock_client.py synthetic data with the same interface
app/config.py      ASSETS registry - add a symbol here to add an instrument
```

* Live data: `option_chain()` polled through a 3 s cache (all browser tabs share it).
* Opening greeks: `historical_data()` on the option contracts for the first minutes of the session
  (cached on disk once fetched). If that fails, the app falls back to the first live snapshot
  seen today and shows a warning.
* Historical: one `historical_data()` sweep over the strikes the underlying traded through,
  at your chosen interval, cached on disk. A first load of a day costs ~10-20 API calls (limit is 60/min).

## Things to verify with your account (couldn't be tested without live credentials)

1. **MCX underlying names** - `GOLD` / `CRUDEOIL` in `config.py`. Check the `asset` column of
   `InstrumentData(nubra).get_instruments_dataframe(exchange="MCX")` (it could be `GOLDM`, `GOLDPETAL`...).
2. **Expired contracts** - NSE symbols are rebuilt from the formats in Nubra's docs
   (`NIFTY2611326000CE` weekly, `NIFTY25MAY24500CE` monthly). Intraday history covers about 3 months.
   Expired **MCX** symbols can't be rebuilt automatically yet - MCX historical works for currently listed expiries.
3. **Price units** - assumed paise (/100) for NSE and MCX. Change `PRICE_DIVISOR` if MCX differs.
4. The SDK may need the account-side flag for some features; contact support@nubra.io if calls are rejected.

## Roadmap

* Stocks (NSE F&O): add entries to `ASSETS`; use `kind="stock"` and `historical type="STOCK"`.
* Crypto: needs a second data source class with the same 5-method interface as `NubraClient`.
* Switch live updates from polling to the `NubraDataSocket` `option` stream (weight 20 per underlying:expiry key).
* Persist live snapshots to build your own intraday history beyond the 3-month window.
