# branches.py
# Your two café locations, used to tell customers which one is closest to
# them for pickup. To add/change a branch later, edit this list — each
# entry needs a name and its latitude/longitude (get these from Google Maps:
# right-click the pin -> the numbers shown are lat, lng).

BRANCHES = [
    {
        "name": "Metropia Coffee — Sayram",
        "address": "Sayram street, 5th passage 4A, Mirzo Ulugbek District, Tashkent",
        "lat": 41.3292041,
        "lng": 69.3226698,
    },
    {
        "name": "Metropia Coffee — Abdulla Qaxxor",
        "address": "Abdulla Qaxxor 150A, Tashkent",
        "lat": 41.2711344,
        "lng": 69.2643661,
    },
]


def nearest_branch(lat: float, lng: float) -> dict:
    """Straight-line (not driving) distance — good enough for 'which branch is closer'."""
    from math import radians, sin, cos, sqrt, atan2

    def distance_km(lat1, lng1, lat2, lng2):
        R = 6371.0
        p1, p2 = radians(lat1), radians(lat2)
        dp = radians(lat2 - lat1)
        dl = radians(lng2 - lng1)
        a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
        return 2 * R * atan2(sqrt(a), sqrt(1 - a))

    return min(BRANCHES, key=lambda b: distance_km(lat, lng, b["lat"], b["lng"]))
