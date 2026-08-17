# Dynamic branch service backed by SQLite. Falls back to the original seed list.
BRANCHES = [
    {"name":"Metropia Coffee — Sayram","address":"Sayram street, 5th passage 4A, Mirzo Ulugbek District, Tashkent","lat":41.3292041,"lng":69.3226698},
    {"name":"Metropia Coffee — Abdulla Qaxxor","address":"Abdulla Qaxxor 150A, Tashkent","lat":41.2711344,"lng":69.2643661},
]

def all_branches():
    try:
        import db
        rows=db.list_branches()
        if rows: return [b for b in rows if b['active']]
    except Exception: pass
    return BRANCHES

def nearest_branch(lat,lng):
    from math import radians,sin,cos,sqrt,atan2
    def d(a,b,c,e):
        R=6371.; p1,p2=radians(a),radians(c); dp=radians(c-a); dl=radians(e-b)
        x=sin(dp/2)**2+cos(p1)*cos(p2)*sin(dl/2)**2
        return 2*R*atan2(sqrt(x),sqrt(1-x))
    rows=all_branches()
    return min(rows,key=lambda b:d(lat,lng,b['lat'],b['lng']))
