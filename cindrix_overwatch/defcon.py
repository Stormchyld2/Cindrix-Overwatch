"""The DEFCON figure shown in the header.

Two readings, always labelled apart:
  - the Overwatch estimate, worked out from the status lights (conflict, military and force-movement reporting), with the reasons;
  - the public tracker at defconlevel.com, read from its home page (it is itself an estimate: the real level is classified).
Neither is official. The estimate never says DEFCON 1: only the public tracker could.
"""

import re

from .feeds import _strip_html

URL = "https://www.defconlevel.com/"
STALE_HOURS = 6
WORDS = {5: "Lowest readiness", 4: "Increased intelligence watch", 3: "Increase in force readiness", 2: "Next step to war", 1: "Maximum readiness"}
# (level, exercise name, what it means, readiness): the commonly cited public summary, not the text of an official order
LEVELS = (
    (5, "FADE OUT", "Lowest state of readiness", "Normal peacetime readiness"),
    (4, "DOUBLE TAKE", "Increased intelligence watch and strengthened security", "Above normal readiness"),
    (3, "ROUND HOUSE", "Force readiness raised above normal", "Air Force ready to mobilize in 15 minutes"),
    (2, "FAST PACE", "Next step to nuclear war", "Forces ready to deploy and engage in under six hours"),
    (1, "COCKED PISTOL", "Nuclear war imminent or already begun", "Maximum readiness, immediate response"),
)
GUIDE_INTRO = ("DEFCON (defense readiness condition) is the five-step scale the US military uses to set how ready its forces are for war. "
               "It counts down: 5 is normal peacetime, 1 is the most severe.")
GUIDE_NOTE = ("The US has never declared DEFCON 1. The highest level on record is DEFCON 2, for Strategic Air Command in October 1962. "
              "The current level is never announced, so any live number, including Overwatch's, is an estimate and not an official figure.")
_LEVEL_WORD = ("QUIET", "WATCH", "ELEVATED", "HIGH")


def parse_public(text):
    """{'level': 1-5, 'updated': 'Nov 6, 2026'} from the tracker's home page, or None if it is not there."""
    plain = _strip_html(text or "")
    m = re.search(r"OSINT\s+Estimate:\s*DEFCON\s*([1-5])\b", plain, re.I) or re.search(r"\bDEFCON\s*([1-5])\b", plain, re.I)
    if not m:
        return None
    u = re.search(r"Updated\s+([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4})", plain)
    return {"level": int(m.group(1)), "updated": u.group(1) if u else ""}


def estimate(indicators):
    """From the status lights. Each light is (id, label, level 0-3, word, note). Returns {'level': 2-5, 'score': x, 'reasons': [...]}."""
    by = {i[0]: i for i in indicators}
    weights = (("conflict", 1.0), ("military", 1.0), ("deploy", 1.5))
    score, reasons = 0.0, []
    for key, w in weights:
        row = by.get(key)
        if not row:
            continue
        score += w * row[2]
        reasons.append(f"{row[1]}: {row[3].title()} ({row[4]})")
    level = 5 if score < 2 else 4 if score < 4.5 else 3 if score < 7 else 2
    return {"level": level, "score": round(score, 1), "reasons": reasons}


def stale(fetched, now):
    return not fetched or now - fetched > STALE_HOURS * 3600
