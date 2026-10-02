"""Thin wrapper over the Nubra Python SDK (nubra-sdk 0.5.x).

Everything the rest of the app needs is exposed through the same small interface that
mock_client.MockClient also implements:

    expiries(asset)                           -> ['20260106', ...]
    option_chain(asset, expiry)               -> normalized chain dict
    resolve_symbol(asset, expiry, strike, ot) -> trading symbol for historical_data()
    option_history(asset, symbols, fields, start, end, interval)
    underlying_series(asset, start, end, interval)

All prices are converted from exchange-native paise to rupees here.
"""
import threading
import time
from datetime import date, datetime

from . import store
from .config import ASSETS, HIST_MIN_INTERVAL, NUBRA_ENV, PRICE_DIVISOR
from .timeutil import is_monthly, iso_utc, ms, parse_expiry

PRICE_FIELDS = {"open", "high", "low", "close"}
MONTH_CODE = "123456789OND"   # weekly-symbol month letter: Jan..Sep -> 1..9, Oct O, Nov N, Dec D


def _rupees(v):
    return None if v is None else v / PRICE_DIVISOR


class NubraClient:
    def __init__(self):
        # imported lazily so the mock mode works without the SDK installed
        from nubra_python_sdk.marketdata.market_data import MarketData
        from nubra_python_sdk.refdata.instruments import InstrumentData
        from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

        env = NubraEnv.PROD if NUBRA_ENV == "PROD" else NubraEnv.UAT
        # First run prompts for the OTP in the terminal; the SDK then reuses the session.
        self.nubra = InitNubraSdk(env, env_creds=True)
        self.md = MarketData(self.nubra)
        self.instruments = InstrumentData(self.nubra)
        self._inst_df = {}
        self._hist_lock = threading.Lock()
        self._last_hist = 0.0
        self._expiry_cache = {}

    # ------------------------------------------------------------ instruments
    def _df(self, exchange):
        if exchange not in self._inst_df:
            self._inst_df[exchange] = self.instruments.get_instruments_dataframe(exchange=exchange)
        return self._inst_df[exchange]

    def expiries(self, asset):
        cached = self._expiry_cache.get(asset)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        cfg = ASSETS[asset]
        res = self.md.option_chain(cfg["underlying"], exchange=cfg["exchange"])
        exp = sorted(str(e) for e in (res.chain.all_expiries or []))
        self._expiry_cache[asset] = (time.time(), exp)
        return exp

    def resolve_symbol(self, asset, expiry, strike, opt):
        """Currently-listed contracts come from the instruments master; expired NSE
        contracts are rebuilt from Nubra's documented symbol formats."""
        cfg = ASSETS[asset]
        df = self._df(cfg["exchange"])
        m = df[(df["asset"] == cfg["underlying"]) & (df["expiry"] == int(expiry)) &
               (df["strike_price"] == int(round(strike * PRICE_DIVISOR))) & (df["option_type"] == opt)]
        if len(m):
            return m.iloc[0]["stock_name"]
        if cfg["exchange"] != "NSE":
            raise LookupError(f"{asset} {expiry} {strike}{opt} is not in the live instruments master "
                              "(expired MCX symbols can't be rebuilt automatically)")
        d = parse_expiry(expiry)
        k = int(strike) if float(strike).is_integer() else strike
        yy = d.strftime("%y")
        if is_monthly(d):
            return f"{cfg['underlying']}{yy}{d.strftime('%b').upper()}{k}{opt}"
        return f"{cfg['underlying']}{yy}{MONTH_CODE[d.month - 1]}{d.day:02d}{k}{opt}"

    # ------------------------------------------------------------ live chain
    def option_chain(self, asset, expiry=None):
        cfg = ASSETS[asset]
        kw = {"exchange": cfg["exchange"]}
        if expiry:
            kw["expiry"] = str(expiry)
        res = self.md.option_chain(cfg["underlying"], **kw)
        ch = res.chain
        rows = {}

        def leg(o):
            return dict(ref_id=o.ref_id, ltp=_rupees(o.last_traded_price), iv=o.iv, delta=o.delta,
                        gamma=o.gamma, theta=o.theta, vega=o.vega, oi=o.open_interest,
                        oi_chg=o.open_interest_change, vol=o.volume)

        for side, lst in (("ce", ch.ce or []), ("pe", ch.pe or [])):
            for o in lst:
                k = _rupees(o.strike_price)
                rows.setdefault(k, {"strike": k, "ce": None, "pe": None})[side] = leg(o)
        return {"asset": asset, "expiry": ch.expiry or expiry, "spot": _rupees(ch.current_price),
                "atm": _rupees(ch.at_the_money_strike), "ts": int(time.time() * 1000),
                "rows": [rows[k] for k in sorted(rows)], "expiries": sorted(map(str, ch.all_expiries or []))}

    # ------------------------------------------------------------ historical
    def _throttled_historical(self, req):
        with self._hist_lock:                    # 60 req/min limit -> one request per ~1.05 s
            wait = HIST_MIN_INTERVAL - (time.time() - self._last_hist)
            if wait > 0:
                time.sleep(wait)
            try:
                return self.md.historical_data(req)
            finally:
                self._last_hist = time.time()

    def _historical(self, exchange, typ, symbols, fields, start: datetime, end: datetime, interval):
        """Returns {symbol: {field: [(ts_ms, value), ...]}} with prices in rupees. Cached on disk
        once the window is in the past."""
        out = {}
        closed = end.timestamp() < time.time() - 300
        for i in range(0, len(symbols), 5):                     # API allows max 5 symbols / request
            batch = symbols[i:i + 5]
            key = f"h|{exchange}|{typ}|{','.join(batch)}|{','.join(fields)}|{iso_utc(start)}|{iso_utc(end)}|{interval}"
            data = store.get(key) if closed else None
            if data is None:
                res = self._throttled_historical({
                    "exchange": exchange, "type": typ, "values": batch, "fields": list(fields),
                    "startDate": iso_utc(start), "endDate": iso_utc(end), "interval": interval,
                    "intraDay": False, "realTime": False})
                data = {}
                for chart in (res.result or []):
                    for d in chart.values:
                        for sym, sc in d.items():
                            data[sym] = {}
                            for f in fields:
                                pts = getattr(sc, f, None) or []
                                conv = _rupees if f in PRICE_FIELDS else (lambda x: x)
                                data[sym][f] = [(p.timestamp // 1_000_000, conv(p.value)) for p in pts]
                if closed:
                    store.put(key, data)
            out.update(data)
        return out

    def option_history(self, asset, symbols, fields, start, end, interval):
        return self._historical(ASSETS[asset]["exchange"], "OPT", symbols, fields, start, end, interval)

    def underlying_series(self, asset, start, end, interval):
        cfg = ASSETS[asset]
        if cfg["kind"] == "index":
            sym, typ = cfg["underlying"], "INDEX"
        else:
            df = self._df(cfg["exchange"])
            fut = df[(df["asset"] == cfg["underlying"]) & (df["derivative_type"] == "FUT") &
                     (df["expiry"] >= int(start.strftime("%Y%m%d")))].sort_values("expiry")
            if fut.empty:
                raise LookupError(f"no futures contract found for {asset}")
            sym, typ = fut.iloc[0]["stock_name"], "FUT"
        data = self._historical(cfg["exchange"], typ, [sym], ["close"], start, end, interval)
        return data.get(sym, {}).get("close", [])
