from app import greeks


def rows():
    out = []
    for k in range(100, 160, 10):   # strikes 100..150
        out.append({"strike": float(k),
                    "ce": {"delta": 0.5, "theta": -1.0, "vega": 2.0},
                    "pe": {"delta": -0.5, "theta": -1.5, "vega": 2.5}})
    return out


def test_nearest_strike():
    assert greeks.nearest_strike([100, 110, 120], 113) == 110


def test_ce_goes_up_pe_goes_down_from_atm():
    ce, pe = greeks.select_strikes([100, 110, 120, 130, 140], 120, 2)
    assert ce == [120, 130, 140]
    assert pe == [120, 110, 100]


def test_sum_and_edges():
    t = greeks.table(rows(), spot=132, depth=2)
    assert t["atm"] == 130.0
    ce, pe = t["sums"]["CE"], t["sums"]["PE"]
    assert ce["strikes_used"] == 3 and pe["strikes_used"] == 3
    assert ce["delta"] == 1.5 and pe["vega"] == 7.5
    # near the edge of the chain fewer strikes exist - must not crash
    t = greeks.table(rows(), spot=150, depth=3)
    assert t["sums"]["CE"]["strikes_used"] == 1


def test_missing_greeks_skipped():
    r = rows()
    r[3]["ce"]["vega"] = None
    t = greeks.table(r, spot=130, depth=1)
    assert t["sums"]["CE"]["strikes_used"] == 1   # 130 skipped, 140 used


def test_change():
    a = greeks.table(rows(), 120, 1)
    b = greeks.table(rows(), 130, 1)
    c = greeks.change(b, a)
    assert c["spot_change"] == 10 and c["sums"]["CE"]["delta"] == 0
