"""Builds option-chain snapshots for the *past* (and today's opening baseline) out of
Nubra historical_data().  Both the live-greeks page (needs the opening baseline) and the
historical pages go through here."""
import bisect
import time
from datetime import date, datetime, timedelta

from . import greeks, store
from .config import ASSETS, IST, MAX_DEPTH
from .timeutil import ms, session_bounds

FIELDS = ["close", "delta", "theta", "vega", "gamma", "iv_mid", "cumulative_oi", "cumulative_volume"]
LEG_MAP = {"ltp": "close", "delta": "delta", "theta": "theta", "vega": "vega", "gamma": "gamma",
           "iv": "iv_mid", "oi": "cumulative_oi", "vol": "cumulative_volume"}


# ----------------------------------------------------------------- helpers
def grid_around(price, depth, step, grid=None, extra=0):
    """Strikes from (ATM - depth) to (ATM + depth) - uses the real strike list if known."""
    if grid:
        g = sorted(grid)
        i = min(range(len(g)), key=lambda j: abs(g[j] - price))
        return g[max(0, i - depth - extra): i + depth + extra + 1]
    atm = round(price / step) * step
    return [float(atm + k * step) for k in range(-depth - extra, depth + extra + 1)]


def grid_between(lo, hi, depth, step, grid=None):
    if grid:
        g = sorted(grid)
        i = min(range(len(g)), key=lambda j: abs(g[j] - lo))
        j = min(range(len(g)), key=lambda j: abs(g[j] - hi))
        return g[max(0, i - depth): j + depth + 1]
    a = int(lo // step) * step - depth * step
    b = (int(hi // step) + 1) * step + depth * step
    return [float(x) for x in range(int(a), int(b) + 1, int(step))]


def value_at(points, t, first_valid=False):
    if not points:
        return None
    if first_valid:
        return next((v for _, v in points if v is not None), None)
    i = bisect.bisect_right([p[0] for p in points], t) - 1
    while i >= 0:
        if points[i][1] is not None:
            return points[i][1]
        i -= 1
    return None


def option_series(client, asset, expiry, strikes, start, end, interval):
    symbols, sym_of = [], {}
    for k in strikes:
        for opt in ("CE", "PE"):
            try:
                s = client.resolve_symbol(asset, expiry, k, opt)
            except LookupError:
                continue
            sym_of[(k, opt)] = s
            symbols.append(s)
    data = client.option_history(asset, sorted(set(symbols)), FIELDS, start, end, interval)
    return {key: data[s] for key, s in sym_of.items() if s in data}


def rows_at(series, strikes, t, first_valid=False):
    rows = []
    for k in strikes:
        row = {"strike": k, "ce": None, "pe": None}
        for opt in ("CE", "PE"):
            ser = series.get((k, opt))
            if not ser:
                continue
            leg = {name: value_at(ser.get(f), t, first_valid) for name, f in LEG_MAP.items()}
            if any(v is not None for v in leg.values()):
                row[opt.lower()] = leg
        rows.append(row)
    return rows


def parity_spot(rows):
    """Underlying estimate from put-call parity: K + CE - PE at the strike where they're closest."""
    best = None
    for r in rows:
        if r["ce"] and r["pe"] and r["ce"]["ltp"] is not None and r["pe"]["ltp"] is not None:
            d = abs(r["ce"]["ltp"] - r["pe"]["ltp"])
            if best is None or d < best[0]:
                best = (d, r["strike"] + r["ce"]["ltp"] - r["pe"]["ltp"])
    return best[1] if best else None


# ----------------------------------------------------------------- today's opening baseline
def open_baseline(client, asset, expiry, depth, day: date, step, grid=None):
    """Table-1 data: ATM chosen from the OPENING underlying price, greeks as of the first candle."""
    ex = ASSETS[asset]["exchange"]
    o, _ = session_bounds(ex, day)
    end = o + timedelta(minutes=6)
    key = f"open|{asset}|{expiry}|{day}|{depth}"
    cached = store.get(key)
    if cached:
        return cached
    try:
        under = [p for p in client.underlying_series(asset, o, end, "1m") if p[1] is not None]
    except Exception:
        under = []
    if not under:
        return None
    spot = under[0][1]
    strikes = grid_around(spot, depth, step, grid)
    series = option_series(client, asset, expiry, strikes, o, end, "1m")
    if not series:
        return None
    rows = rows_at(series, strikes, None, first_valid=True)
    tbl = greeks.table(rows, spot, depth)
    tbl.update(ts=under[0][0], source="historical-open")
    if time.time() > ms(end) / 1000 + 60:
        store.put(key, tbl)
    return tbl


# ----------------------------------------------------------------- any past (or current) day
_mem = {}


def historical_day(client, asset, expiry, day: date, depth, interval="5m", at_ms=None, center=None):
    depth = max(1, min(depth, MAX_DEPTH))
    cfg = ASSETS[asset]
    o, c = session_bounds(cfg["exchange"], day)
    end = min(c, datetime.now(IST))
    if end <= o:
        raise ValueError("No trading session data for that date yet.")
    step = cfg["step"]
    mkey = (asset, expiry, str(day), interval, depth, center)
    hit = _mem.get(mkey)
    if hit and time.time() - hit[0] < 120:
        under, strikes, series = hit[1]
    else:
        try:
            under = [p for p in client.underlying_series(asset, o, end, interval) if p[1] is not None]
        except Exception:
            under = []
        if under:
            prices = [p[1] for p in under]
            strikes = grid_between(min(prices), max(prices), depth, step)
        elif center:
            strikes = grid_around(float(center), depth, step, extra=8)
        else:
            raise ValueError("Underlying history unavailable for this date - pass a `center` strike "
                             "so the app can estimate spot from put-call parity.")
        series = option_series(client, asset, expiry, strikes, o, end, interval)
        _mem[mkey] = (time.time(), (under, strikes, series))
    if not series:
        raise ValueError("No option history found for that expiry/date (contract may be too old - "
                         "intraday history covers ~3 months).")

    if under:
        timeline = [t for t, _ in under]
        spot_of = dict(under)
    else:
        timeline = sorted({t for s in series.values() for t, _ in s.get("close", [])})
        spot_of = {t: parity_spot(rows_at(series, strikes, t)) for t in timeline}
    timeline = [t for t in timeline if spot_of.get(t) is not None]
    if not timeline:
        raise ValueError("No usable candles for that date.")

    open_t = timeline[0]
    open_tbl = greeks.table(rows_at(series, strikes, open_t, first_valid=True), spot_of[open_t], depth)
    open_tbl["ts"] = open_t

    pts = []
    for t in timeline:
        tb = greeks.table(rows_at(series, strikes, t), spot_of[t], depth)
        ch = greeks.change(tb, open_tbl)
        p = {"t": t, "spot": spot_of[t]}
        for side in ("CE", "PE"):
            for g in greeks.GREEKS:
                p[f"{side}_{g}"] = tb["sums"][side][g]
                p[f"{side}_{g}_chg"] = ch["sums"][side][g]
        pts.append(p)

    sel_t = max([t for t in timeline if at_ms is None or t <= at_ms] or [timeline[0]])
    sel_rows = rows_at(series, strikes, sel_t)
    sel_tbl = greeks.table(sel_rows, spot_of[sel_t], depth)
    sel_tbl["ts"] = sel_t
    return {"asset": asset, "expiry": expiry, "date": str(day), "depth": depth, "interval": interval,
            "open": open_tbl, "selected": sel_tbl, "change": greeks.change(sel_tbl, open_tbl),
            "chain": {"ts": sel_t, "spot": spot_of[sel_t], "atm": sel_tbl["atm"], "rows": sel_rows},
            "timeline": timeline, "series": pts}
