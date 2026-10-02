"""Pure functions - no network.  This is the core of the 3-table greeks page.

Definitions
-----------
* ATM strike  : strike nearest to the underlying price.
* CE side     : ATM and the `depth` strikes ABOVE it   (ATM -> OTM calls)
* PE side     : ATM and the `depth` strikes BELOW it   (ATM -> OTM puts)
* Table 1     : sums using the opening underlying price (ATM chosen at open) and opening greeks
* Table 2     : sums using the current/selected underlying price and greeks
* Table 3     : Table 2 - Table 1
"""
from typing import Optional

GREEKS = ("delta", "theta", "vega")


def nearest_strike(strikes, price: float) -> Optional[float]:
    return min(strikes, key=lambda s: abs(s - price)) if strikes else None


def select_strikes(strikes, atm, depth):
    """Return (ce_strikes, pe_strikes) from ATM to OTM, `depth` strikes beyond ATM."""
    ordered = sorted(strikes)
    if atm not in ordered:
        return [], []
    i = ordered.index(atm)
    return ordered[i:i + depth + 1], ordered[max(0, i - depth):i + 1][::-1]


def sum_greeks(rows, atm, depth):
    """rows: [{'strike': float, 'ce': {...}|None, 'pe': {...}|None}]"""
    by_strike = {r["strike"]: r for r in rows}
    ce_s, pe_s = select_strikes(list(by_strike), atm, depth)
    out = {}
    for side, strikes in (("CE", ce_s), ("PE", pe_s)):
        key = side.lower()
        tot = {g: 0.0 for g in GREEKS}
        used = 0
        for s in strikes:
            leg = by_strike[s].get(key)
            if not leg:
                continue
            vals = [leg.get(g) for g in GREEKS]
            if any(v is None for v in vals):
                continue
            for g, v in zip(GREEKS, vals):
                tot[g] += v
            used += 1
        out[side] = {**{g: round(v, 4) for g, v in tot.items()},
                     "strikes_used": used,
                     "from_strike": strikes[0] if strikes else None,
                     "to_strike": strikes[-1] if strikes else None}
    return out


def table(rows, spot, depth, atm=None):
    strikes = [r["strike"] for r in rows]
    atm = atm if atm is not None else nearest_strike(strikes, spot)
    return {"spot": spot, "atm": atm, "depth": depth, "sums": sum_greeks(rows, atm, depth)}


def change(current: dict, opening: dict):
    out = {}
    for side in ("CE", "PE"):
        out[side] = {g: round(current["sums"][side][g] - opening["sums"][side][g], 4) for g in GREEKS}
    return {"spot_change": None if current["spot"] is None or opening["spot"] is None
            else round(current["spot"] - opening["spot"], 2), "sums": out}
