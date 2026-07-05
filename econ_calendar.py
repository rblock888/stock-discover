"""High-impact economic event calendar — from OFFICIAL public schedules.

The books are explicit: institutional traps cluster around scheduled news
(FOMC, CPI, NFP), and retail gets run over trading through them. A paid
"economic calendar with countdowns" is a subscription feature elsewhere;
the underlying schedules are public:

  FOMC   federalreserve.gov/monetarypolicy/fomccalendars.htm (verified
         2026-07-03) — the DECISION lands on the meeting's second day, 14:00 ET
  CPI    BLS release schedule (mirror-verified; Jul 14 cross-checked vs BLS)
         — 08:30 ET
  NFP    Employment Situation — first Friday of the month, 08:30 ET (computed)

Dates are tentative-until-confirmed per the Fed's own disclaimer; refresh this
file yearly (or when the Fed moves a meeting).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# FOMC decision days (second day of each meeting), announced schedule
FOMC_DECISIONS = [
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    # 2027 (preliminary)
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
]

# CPI release days, 08:30 ET (2026 schedule)
CPI_RELEASES = [
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10",
    "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
    "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
]


def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def _nfp_dates(around: date, months: int = 3) -> list:
    """Employment Situation ≈ first Friday of the month (computed).
    Rare holiday shifts (e.g. July-4th weeks) are not modeled — ±1 day."""
    out = []
    y, m = around.year, around.month
    for i in range(-1, months):
        mm = m + i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        out.append(_first_friday(yy, mm))
    return out


def upcoming(days: int = 7, today: date = None) -> list:
    """[{date, name, time_et, days_away}] for high-impact events in the window."""
    today = today or datetime.now(ET).date()
    horizon = today + timedelta(days=days)
    events = []
    for iso in FOMC_DECISIONS:
        d = date.fromisoformat(iso)
        if today <= d <= horizon:
            events.append({"date": iso, "name": "FOMC decision", "time_et": "14:00"})
    for iso in CPI_RELEASES:
        d = date.fromisoformat(iso)
        if today <= d <= horizon:
            events.append({"date": iso, "name": "CPI", "time_et": "08:30"})
    for d in _nfp_dates(today):
        if today <= d <= horizon:
            events.append({"date": d.isoformat(), "name": "Jobs report (NFP)", "time_et": "08:30"})
    for e in events:
        e["days_away"] = (date.fromisoformat(e["date"]) - today).days
    events.sort(key=lambda e: e["date"])
    return events


def today_events(today: date = None) -> list:
    """High-impact events landing TODAY — the books' 'don't trade the news' flag."""
    return [e for e in upcoming(days=0, today=today) if e["days_away"] == 0]
