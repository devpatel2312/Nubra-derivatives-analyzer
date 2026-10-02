"""Synthetic data source with the same interface as NubraClient.
Lets you run and demo the whole UI without credentials (USE_MOCK=1).
Spot follows a deterministic pseudo-random walk, option greeks come from Black-Scholes."""
import math
import random
import time
from datetime import date, datetime, timedelta

from .config import ASSETS, IST
from .timeutil import from_ms, ms, parse_expiry, session_bounds

BASE = {"NIFTY": (24500, 0.15), "BANKNIFTY": (55000, 0.18), "GOLD": (120000, 0.16), "CRUDEOIL": (6000, 0.35)}


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs(S, K, T, sigma, opt, r=0.065):
    T = max(T, 1e-4)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt == "CE":
        price = S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
        delta = _ncdf(d1)
        theta = (-S * _npdf(d1) * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _ncdf(d2)) / 365
    else:
        price = K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)
        delta = _ncdf(d1) - 1
        theta = (-S * _npdf(d1) * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _ncdf(-d2)) / 365
    return dict(ltp=price, delta=delta, theta=theta, vega=S * _npdf(d1) * math.sqrt(T) / 100,
                gamma=_npdf(d1) / (S * sigma * math.sqrt(T)), iv=sigma * 100)


class MockClient:
    def _spot(self, asset, t_ms):
        base, vol = BASE[asset]
        day = from_ms(t_ms).date()
        rnd = random.Random(f"{asset}{day}")
        drift = rnd.uniform(-0.01, 0.01)
        o, c = session_bounds(ASSETS[asset]["exchange"], day)
        frac = min(max((t_ms - ms(o)) / max(ms(c) - ms(o), 1), 0), 1)
        gap = rnd.uniform(-0.004, 0.004)
        wave = math.sin(frac * 9 + rnd.random()) * 0.004
        return round(base * (1 + gap + drift * frac + wave) / ASSETS[asset]["step"]) * ASSETS[asset]["step"] \
            + (base * 0.0003) * math.sin(t_ms / 9e4)

    def expiries(self, asset):
        d, out = date.today(), []
        while len(out) < 4:
            d += timedelta(days=1)
            if d.weekday() == 1:
                out.append(d.strftime("%Y%m%d"))
        return out

    def _T(self, expiry, t_ms):
        end = datetime.combine(parse_expiry(expiry), datetime.min.time(), IST).replace(hour=15, minute=30)
        return max((ms(end) - t_ms) / 1000 / 86400 / 365, 1e-4)

    def _leg(self, asset, expiry, K, opt, t_ms):
        S, vol = self._spot(asset, t_ms), BASE[asset][1]
        skew = 1 + 0.15 * abs(math.log(K / S)) * 5
        g = bs(S, K, self._T(expiry, t_ms), vol * skew, opt)
        rnd = random.Random(f"{asset}{expiry}{K}{opt}")
        g.update(ref_id=hash((asset, expiry, K, opt)) % 10**6, oi=int(rnd.uniform(1e4, 9e5)),
                 oi_chg=round(rnd.uniform(-8, 12), 2), vol=int(rnd.uniform(1e3, 5e5)))
        return g

    def option_chain(self, asset, expiry=None):
        expiry = expiry or self.expiries(asset)[0]
        now, step = int(time.time() * 1000), ASSETS[asset]["step"]
        S = self._spot(asset, now)
        atm = round(S / step) * step
        rows = [{"strike": float(k), "ce": self._leg(asset, expiry, k, "CE", now),
                 "pe": self._leg(asset, expiry, k, "PE", now)}
                for k in (atm + i * step for i in range(-20, 21))]
        return {"asset": asset, "expiry": expiry, "spot": round(S, 2), "atm": float(atm), "ts": now,
                "rows": rows, "expiries": self.expiries(asset)}

    def resolve_symbol(self, asset, expiry, strike, opt):
        return f"{asset}|{expiry}|{float(strike)}|{opt}"

    def _grid(self, start, end, interval):
        mins = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}[interval]
        t, out = start, []
        while t <= min(end, datetime.now(IST)):
            if t.weekday() < 5:          # per-asset session filtering happens in the callers
                out.append(ms(t))
            t += timedelta(minutes=mins)
        return out

    def option_history(self, asset, symbols, fields, start, end, interval):
        ex = ASSETS[asset]["exchange"]
        out = {}
        for sym in symbols:
            a, expiry, K, opt = sym.split("|")
            ser = {f: [] for f in fields}
            for t in self._grid(start, end, interval):
                o, c = session_bounds(ex, from_ms(t).date())
                if not (ms(o) <= t <= ms(c)):
                    continue
                L = self._leg(a, expiry, float(K), opt, t)
                m = {"close": L["ltp"], "delta": L["delta"], "theta": L["theta"], "vega": L["vega"],
                     "gamma": L["gamma"], "iv_mid": L["iv"], "cumulative_oi": L["oi"], "cumulative_volume": L["vol"]}
                for f in fields:
                    ser[f].append((t, m.get(f)))
            out[sym] = ser
        return out

    def underlying_series(self, asset, start, end, interval):
        ex = ASSETS[asset]["exchange"]
        pts = []
        for t in self._grid(start, end, interval):
            o, c = session_bounds(ex, from_ms(t).date())
            if ms(o) <= t <= ms(c):
                pts.append((t, self._spot(asset, t)))
        return pts
