from datetime import date, datetime, timedelta, timezone

from .config import IST, SESSIONS


def session_bounds(exchange: str, day: date):
    o, c = SESSIONS[exchange]
    return (datetime.combine(day, o, IST), datetime.combine(day, c, IST))


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def from_ms(v: int) -> datetime:
    return datetime.fromtimestamp(v / 1000, IST)


def parse_expiry(e: str) -> date:
    return datetime.strptime(str(e), "%Y%m%d").date()


def is_monthly(expiry: date) -> bool:
    """Last expiry of its month  (a week later falls in the next month)."""
    return (expiry + timedelta(days=7)).month != expiry.month
