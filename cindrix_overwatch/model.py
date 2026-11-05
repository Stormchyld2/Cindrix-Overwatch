"""The one record type every source is turned into."""

import hashlib
from dataclasses import dataclass, field

KINDS = ("military", "conflict", "hazard", "weather", "space", "health", "news")
KIND_LABELS = {"military": "MILITARY", "conflict": "CONFLICT", "hazard": "HAZARD", "weather": "WEATHER",
               "space": "SPACE", "health": "HEALTH", "news": "NEWS"}
TRUST = ("official", "wire", "outlet")
TRUST_LABELS = {"official": "Official source", "wire": "Wire or agency", "outlet": "Single outlet"}
SEVERITY_WORDS = ("Info", "Notice", "Warning", "Severe")


@dataclass
class Item:
    source_id: str
    source: str
    kind: str
    trust: str
    title: str
    url: str = ""
    summary: str = ""
    ts: float = 0.0                 # when it was published, epoch seconds
    lat: float = None
    lon: float = None
    place: str = ""
    severity: int = 0               # 0 info, 1 notice, 2 warning, 3 severe
    states: list = field(default_factory=list)
    count: int = 1                  # how many sources report the same story (set when grouping)
    uid: str = ""
    first_seen: float = 0.0         # when Overwatch first saw it (set by the store)
    title_en: str = ""              # English translation of the title, when one was made (kept apart from the original)
    summary_en: str = ""

    def __post_init__(self):
        self.title = " ".join((self.title or "").split())[:300]
        self.summary = " ".join((self.summary or "").split())[:500]
        if self.kind not in KINDS:
            self.kind = "news"
        if self.trust not in TRUST:
            self.trust = "outlet"
        self.severity = max(0, min(3, int(self.severity)))
        if not self.uid:
            key = f"{self.source_id}|{self.url or self.title}|{self.title if not self.url else ''}"
            self.uid = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:20]

    @property
    def shown(self):
        """The title to show: the English one when there is one, else the original."""
        return self.title_en or self.title

    @property
    def pinned(self):
        return self.lat is not None and self.lon is not None
