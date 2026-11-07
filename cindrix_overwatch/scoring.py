"""Sorting items into kinds, grouping the same story, matching to your home, and the SHTF indicator lights.

Everything here is simple and readable on purpose: keyword rules and counts, no hidden scoring. The
indicators say what they are based on, because they measure how much is being reported, not what is true.
"""

import re

from . import geo

_W = lambda *w: re.compile(r"\b(?:" + "|".join(w) + r")", re.I)

CONFLICT_RE = _W("attack", "airstrike", "air strike", "missile", "shelling", "invasion", "offensive", "bombing",
                 "drone strike", "hostage", "ceasefire", "shot down", "casualt", "troops", "war\\b", "killed",
                 "clashes", "insurgent", "rebels", "coup")
MILITARY_RE = _W("navy", "naval", "army", "air force", "marine", "warship", "destroyer", "aircraft carrier",
                 "fighter jet", "exercise", "deploy", "nato", "pentagon", "defense ministry", "defence ministry",
                 "submarine", "military", "coast guard", "space force", "bomber", "armed forces")
HEALTH_RE = _W("outbreak", "epidemic", "pandemic", "virus", "cholera", "ebola", "measles", "bird flu", "h5n1",
               "mpox", "quarantine", "marburg", "dengue")
HAZARD_RE = _W("earthquake", "tsunami", "hurricane", "typhoon", "cyclone", "wildfire", "flood", "volcano",
               "tornado", "landslide", "eruption")
GRID_RE = _W("power outage", "blackout", "power grid", "grid failure", "without power", "power cuts")
SUPPLY_RE = _W("shortage", "fuel prices", "food prices", "supply chain", "rationing", "panic buying",
               "price gouging")
SEVERE_RE = _W("nuclear", "invasion", "mass casualt", "explosion", "killed", "dead\\b", "massacre", "chemical")


# Words that point to forces being moved, raised or readied (not just "military news"). Used for the Deployments
# filter and the Force movements light. These are headline signals; they say what was reported, not what is true.
DEPLOY_RE = _W("deploys?", "deployed", "deploying", "deployment", "mobili[sz]", "reservists?", "call-?up", "build-?up",
               "troops (?:to|near|along|on)", "sends? (?:troops|forces|warships|ships|jets|aircraft)", "strike group",
               "carrier group", "amphibious", "moves? (?:forces|troops|warships)", "reinforce", "redeploy", "dispatch",
               "no-?fly zone", "notam", "naval exercise", "military exercise", "war games", "blockade", "drawdown",
               "ordered departure", "evacuat", "martial law", "state of emergency", "conscription", "military draft",
               "draft (?:call|order|notice)", "airlift", "troop rotation", "snap (?:drill|exercise|inspection)", "live-?fire",
               "scrambl", "heightened alert", "put on alert", "on high alert", "armada",
               "troop (?:movement|concentration|buildup)", "border (?:closure|closed)", "airspace (?:closed|closure)",
               "nuclear (?:alert|readiness|drill|exercise)", "missile (?:test|launch)", "readiness")


def is_deployment(item):
    return bool(DEPLOY_RE.search(item.title)) and item.kind in ("military", "conflict", "news")


LEVEL_RE = re.compile(r"Level ([1-4])\b")


def classify(item):
    """Gives a general news headline a more useful kind. Sources with a set kind keep it."""
    if item.source_id == "travel":
        m = LEVEL_RE.search(item.title)
        if m:
            item.severity = {"4": 3, "3": 2, "2": 1}.get(m.group(1), 0)
        return item
    if item.kind != "news":
        return item
    t = item.title
    if CONFLICT_RE.search(t):
        item.kind = "conflict"
    elif MILITARY_RE.search(t):
        item.kind = "military"
    elif HEALTH_RE.search(t):
        item.kind = "health"
    elif HAZARD_RE.search(t):
        item.kind = "hazard"
    if item.kind == "conflict":
        item.severity = max(item.severity, 2 if SEVERE_RE.search(t) else 1)
    elif item.kind in ("health", "hazard"):
        item.severity = max(item.severity, 1)
    if is_deployment(item) and item.kind in ("military", "conflict"):
        item.severity = max(item.severity, 1)
    return item


def is_home(item, home_states):
    return bool(set(item.states) & set(home_states))


_STOP = set("""the and for with from that this have has are was were will after over into about says said new
amid more than their they its his her who what when where how not but out off one two three""".split())


def _tokens(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 3 and w not in _STOP}


def _rank(item):
    return ({"official": 2, "wire": 1, "outlet": 0}[item.trust], item.severity, item.ts)


def group(items, window_hours=48):
    """Collapses reports of the same story into one item with a count. Structured hazard data is left alone."""
    out, clusters = [], []
    for it in sorted(items, key=lambda i: -i.ts):
        if it.kind in ("hazard", "weather", "space"):
            out.append(it)
            continue
        toks = _tokens(it.title)
        placed = False
        for c in clusters:
            if abs(c["ts"] - it.ts) > window_hours * 3600:
                continue
            common = len(toks & c["toks"])
            if toks and c["toks"] and common >= 3 and common / len(toks | c["toks"]) >= 0.4:
                c["members"].append(it)
                c["toks"] |= toks
                placed = True
                break
        if not placed:
            clusters.append({"ts": it.ts, "toks": set(toks), "members": [it]})
    for c in clusters:
        sources = {m.source_id for m in c["members"]}
        rep = max(c["members"], key=_rank)
        rep.count = len(sources) if len(sources) > 1 else len(c["members"])
        out.append(rep)
    out.sort(key=lambda i: -i.ts)
    return out


def _level(n, cuts):
    lvl = 0
    for c in cuts:
        if n >= c:
            lvl += 1
    return lvl


def indicators(items, home_states, now):
    """Eight status lights. Each is (id, label, level 0-3, word, note)."""
    day = [i for i in items if now - i.ts <= 24 * 3600]
    two = [i for i in items if now - i.ts <= 48 * 3600]
    week = [i for i in items if now - i.ts <= 7 * 24 * 3600]
    out = []

    wx = [i for i in two if i.kind == "weather" and is_home(i, home_states)]
    lvl = max([i.severity for i in wx], default=0)
    out.append(("weather", "Home weather", min(lvl, 3), ("NORMAL", "ADVISORY", "WARNING", "SEVERE")[min(lvl, 3)],
                f"{len(wx)} active alert{'s' if len(wx) != 1 else ''} at home" if wx else "No alerts at home"))

    grid = [i for i in two if GRID_RE.search(i.title)]
    lvl = _level(len(grid), (1, 3, 10))
    out.append(("grid", "Power grid", lvl, ("NORMAL", "WATCH", "ELEVATED", "HIGH")[lvl],
                f"{len(grid)} outage headlines, 48 h" if grid else "No outage headlines"))

    hp = geo.home_point(home_states)
    near = []
    if hp:
        for i in week:
            if i.source_id == "usgs" and i.pinned and geo.haversine_km(hp[0], hp[1], i.lat, i.lon) <= 500:
                near.append(i)
    lvl = max([i.severity for i in near], default=-1) + 1 if near else 0
    out.append(("quakes", "Quakes near home", min(lvl, 3), ("QUIET", "WATCH", "ELEVATED", "HIGH")[min(lvl, 3)],
                f"{len(near)} within 500 km, 7 days" if near else ("None within 500 km, 7 days" if hp else "Set a home state")))

    hl = [i for i in group([i for i in week if i.kind == "health"]) ]
    lvl = _level(len(hl), (1, 3, 6))
    out.append(("outbreaks", "Outbreaks", lvl, ("NORMAL", "WATCH", "ELEVATED", "HIGH")[lvl],
                f"{len(hl)} health items, 7 days" if hl else "No new alerts"))

    sp = [i for i in two if i.kind == "space"]
    lvl = max([i.severity for i in sp], default=0)
    out.append(("space", "Space weather", lvl, ("NORMAL", "WATCH", "STORM", "SEVERE")[lvl],
                max(sp, key=lambda i: i.severity).title.split(":")[0] if sp else "Calm"))

    cf = group([i for i in day if i.kind == "conflict"])
    lvl = _level(len(cf), (5, 15, 30))
    out.append(("conflict", "Conflict reporting", lvl, ("NORMAL", "WATCH", "ELEVATED", "HIGH")[lvl],
                f"{len(cf)} stories, 24 h"))

    ml = group([i for i in day if i.kind == "military"])
    lvl = _level(len(ml), (5, 15, 30))
    out.append(("military", "Military activity", lvl, ("QUIET", "ACTIVE", "BUSY", "HIGH")[lvl],
                f"{len(ml)} items, 24 h"))

    dp = group([i for i in day if is_deployment(i)])
    lvl = _level(len(dp), (3, 8, 16))
    out.append(("deploy", "Force movements", lvl, ("QUIET", "WATCH", "ELEVATED", "HIGH")[lvl],
                f"{len(dp)} deployment or readiness stories, 24 h" if dp else "No deployment signals"))

    sup = [i for i in two if SUPPLY_RE.search(i.title)]
    lvl = _level(len(sup), (2, 5, 10))
    out.append(("supply", "Supply news", lvl, ("NORMAL", "WATCH", "ELEVATED", "HIGH")[lvl],
                f"{len(sup)} headlines, 48 h" if sup else "Nothing unusual"))
    return out


_KIND_WEIGHT = {"military": 1.5, "conflict": 1.5, "hazard": 1.0, "health": 1.0, "weather": 1.0, "space": 0.5, "news": 0.0}
_TRUST_WEIGHT = {"official": 1.5, "wire": 1.0, "outlet": 0.0}


def warning_score(item, home_states, now):
    """How much an item matters for early warning of a long emergency. Plain arithmetic, no AI: severity, force movements,
    the home area, how many sources agree, how much the source can be trusted, and how fresh it is."""
    s = item.severity * 3.0
    if is_deployment(item):
        s += 4
    if is_home(item, home_states):
        s += 3
    s += _TRUST_WEIGHT.get(item.trust, 0.0) + min(max(item.count - 1, 0), 4) * 1.5 + _KIND_WEIGHT.get(item.kind, 0.0)
    s += max(0.0, 2.0 - max(0.0, now - item.ts) / 3600 / 12)
    return s


def why_it_matters(item, home_states):
    """Short plain reasons an item is near the top."""
    out = []
    if item.severity >= 2:
        out.append("severe" if item.severity == 3 else "warning")
    if is_deployment(item):
        out.append("force movement")
    if is_home(item, home_states):
        out.append("home area")
    if item.count > 1:
        out.append(f"{item.count} sources")
    if item.trust == "official":
        out.append("official source")
    return out


def top_warnings(items, home_states, now, n=10, per_source=3):
    """The n items most relevant for early warning, best first, as (item, reasons). Sports and entertainment, cyber
    stories and anything older than two days are left out, and no one source can fill the list."""
    from .ai import off_topic
    pool = [i for i in items if i.kind not in ("cyber", "prepper") and now - i.ts <= 48 * 3600 and not off_topic(i)]
    pool.sort(key=lambda i: (-warning_score(i, home_states, now), -i.ts))
    out, taken = [], {}
    for it in pool:
        if taken.get(it.source_id, 0) >= per_source:
            continue
        taken[it.source_id] = taken.get(it.source_id, 0) + 1
        out.append((it, why_it_matters(it, home_states)))
        if len(out) >= n:
            break
    return out
