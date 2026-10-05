"""Which toolkit tiles a STAALCALIBUR key sees, and when.

The tools are revealed step by step after the key is bought on the website
(the app itself sells nothing, so Google Play only ever sees an app that
unlocks what was paid for elsewhere):

    free trial     no tool tiles
    day 0          Risk Sizer (free)
    day 7          Prime Hours (available to rent), Guardian shown as coming soon
    day 12         Guardian available to rent

An add-on the key already rents is always "open". The customer is told on
Telegram when a tool becomes available (licensing/server.py tool_notices).
Pure: no network, no clock.
"""
DAY = 86400
HOURS_DAY = 7
GUARDIAN_DAY = 12


def tiles(valid, trial, since, owns_hours, owns_guardian, now, for_sale=()):
    """{"sizer", "hours", "guardian"} -> "free" | "open" | "available" | "soon" | None (hidden).
    An add-on not yet for sale (`for_sale` lacks its code) stays "soon" past its day."""
    t = {"sizer": None, "hours": None, "guardian": None}
    if valid and not trial:
        days = (now - (since or now)) / DAY
        t["sizer"] = "free"
        if days >= HOURS_DAY:
            t["hours"] = "available" if "HOURS" in for_sale else "soon"
            t["guardian"] = "soon"
        if days >= GUARDIAN_DAY and "GUARDIAN" in for_sale:
            t["guardian"] = "available"
    if owns_hours:
        t["hours"] = "open"
    if owns_guardian:
        t["guardian"] = "open"
    if owns_hours or owns_guardian:
        t["sizer"] = "free"
    return t
