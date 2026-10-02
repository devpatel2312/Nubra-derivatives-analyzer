import os
os.environ["USE_MOCK"] = "1"
os.environ["DB_PATH"] = "/tmp/test_cache.db"

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def last_weekday():
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def test_assets():
    j = c.get("/api/assets").json()
    assert [a["id"] for a in j["assets"]] == ["NIFTY", "BANKNIFTY", "GOLD", "CRUDEOIL"]


def test_live_chain_and_greeks():
    exp = c.get("/api/expiries", params={"asset": "NIFTY"}).json()[0]
    ch = c.get("/api/chain/live", params={"asset": "NIFTY", "expiry": exp}).json()
    assert len(ch["rows"]) == 41
    g = c.get("/api/greeks/live", params={"asset": "NIFTY", "expiry": exp, "depth": 5}).json()
    assert g["current"]["sums"]["CE"]["strikes_used"] == 6
    assert g["open"]["source"] in ("historical-open", "first-live-snapshot")
    for side in ("CE", "PE"):
        for k in ("delta", "theta", "vega"):
            assert abs(g["change"]["sums"][side][k] -
                       (g["current"]["sums"][side][k] - g["open"]["sums"][side][k])) < 1e-3


def test_historical_all_assets():
    d = last_weekday()
    for asset in ("NIFTY", "BANKNIFTY", "GOLD", "CRUDEOIL"):
        exp = c.get("/api/expiries", params={"asset": asset}).json()[0]
        r = c.get("/api/historical", params={"asset": asset, "expiry": exp, "day": str(d), "depth": 4,
                                             "time": "11:00"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["series"] and j["chain"]["rows"] and j["selected"]["atm"]


def test_bad_asset():
    assert c.get("/api/expiries", params={"asset": "FOO"}).status_code == 404
