import json
import math
import os
import threading
import time
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import greeks, history, store
from .config import ASSETS, IST, LIVE_TTL, MAX_DEPTH, USE_MOCK

app = FastAPI(title="Derivatives Analyzer")

_client = None
_client_lock = threading.Lock()


def client():
    global _client
    with _client_lock:
        if _client is None:
            if USE_MOCK:
                from .mock_client import MockClient
                _client = MockClient()
            else:
                from .nubra_client import NubraClient
                _client = NubraClient()
        return _client


def clean(o):
    """JSON-safe: NaN/inf -> None."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


def ok(payload):
    return JSONResponse(clean(payload))


def check_asset(asset):
    if asset not in ASSETS:
        raise HTTPException(404, f"unknown asset {asset}")


def guarded(fn):
    try:
        return fn()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # SDK / network errors
        raise HTTPException(502, f"{type(e).__name__}: {e}")


_live_cache = {}


def live_chain(asset, expiry):
    key = (asset, expiry)
    hit = _live_cache.get(key)
    if hit and time.time() - hit[0] < LIVE_TTL:
        return hit[1]
    ch = client().option_chain(asset, expiry)
    _live_cache[key] = (time.time(), ch)
    return ch


def grid_step(rows, default):
    ks = sorted(r["strike"] for r in rows)
    diffs = [b - a for a, b in zip(ks, ks[1:]) if b > a]
    return min(diffs) if diffs else default


@app.get("/api/assets")
def assets():
    return ok({"mock": USE_MOCK,
               "assets": [{"id": k, "label": v["label"], "exchange": v["exchange"]} for k, v in ASSETS.items()]})


@app.get("/api/expiries")
def expiries(asset: str):
    check_asset(asset)
    return ok(guarded(lambda: client().expiries(asset)))


@app.get("/api/chain/live")
def chain_live(asset: str, expiry: str | None = None):
    check_asset(asset)
    return ok(guarded(lambda: live_chain(asset, expiry)))


@app.get("/api/greeks/live")
def greeks_live(asset: str, expiry: str | None = None, depth: int = Query(5, ge=1, le=MAX_DEPTH)):
    check_asset(asset)

    def run():
        ch = live_chain(asset, expiry)
        exp = ch["expiry"] or expiry
        today = datetime.now(IST).date()
        step = grid_step(ch["rows"], ASSETS[asset]["step"])
        grid = [r["strike"] for r in ch["rows"]]

        current = greeks.table(ch["rows"], ch["spot"], depth)
        current["ts"] = ch["ts"]

        try:
            opening = history.open_baseline(client(), asset, exp, depth, today, step, grid)
        except Exception:
            opening = None
        if opening is None:
            # fallback: first live snapshot seen today (flagged so the UI can warn)
            key = f"first|{asset}|{exp}|{today}"
            first = store.get(key)
            if first is None:
                first = {"ts": ch["ts"], "spot": ch["spot"], "rows": ch["rows"]}
                store.put(key, first)
            opening = greeks.table(first["rows"], first["spot"], depth)
            opening.update(ts=first["ts"], source="first-live-snapshot")
        return {"asset": asset, "expiry": exp, "depth": depth, "open": opening, "current": current,
                "change": greeks.change(current, opening)}

    return ok(guarded(run))


@app.get("/api/historical")
def historical(asset: str, expiry: str, day: str, depth: int = Query(5, ge=1, le=MAX_DEPTH),
               interval: str = "5m", time_: str | None = Query(None, alias="time"), center: float | None = None):
    """One call powers both the historical option chain and historical greeks pages.
    `time` is HH:MM IST; omit for the last candle of the day."""
    check_asset(asset)

    def run():
        d = date.fromisoformat(day)
        at_ms = None
        if time_:
            hh, mm = map(int, time_.split(":"))
            at_ms = int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).timestamp() * 1000)
        return history.historical_day(client(), asset, expiry, d, depth, interval, at_ms, center)

    return ok(guarded(run))


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "static"), html=True), name="static")
