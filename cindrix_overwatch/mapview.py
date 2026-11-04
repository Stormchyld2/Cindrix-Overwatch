"""The world map: a plain Tk canvas with pan, zoom, and clickable pins. No map tiles, so it works offline."""

import tkinter as tk

from . import theme
from .mapdata import load_land

MIN_SCALE_FACTOR, MAX_SCALE = 1.0, 60.0     # pixels per degree


class Projection:
    """Equirectangular: x = longitude, y = latitude, centred on (lon0, lat0)."""

    def __init__(self, width=800, height=400):
        self.w, self.h = width, height
        self.lon0, self.lat0 = 0.0, 15.0
        self.scale = self.min_scale()

    def min_scale(self):
        return max(self.w / 360.0, self.h / 180.0, 0.5)

    def resize(self, w, h):
        self.w, self.h = max(w, 50), max(h, 50)
        self.scale = max(self.scale, self.min_scale())
        self.clamp()

    def to_px(self, lat, lon):
        return self.w / 2 + (lon - self.lon0) * self.scale, self.h / 2 - (lat - self.lat0) * self.scale

    def to_geo(self, x, y):
        return self.lat0 - (y - self.h / 2) / self.scale, self.lon0 + (x - self.w / 2) / self.scale

    def clamp(self):
        half_lon, half_lat = self.w / 2 / self.scale, self.h / 2 / self.scale
        self.lon0 = max(-180 + half_lon, min(180 - half_lon, self.lon0)) if half_lon < 180 else 0.0
        self.lat0 = max(-90 + half_lat, min(90 - half_lat, self.lat0)) if half_lat < 90 else 0.0

    def zoom_at(self, x, y, factor):
        lat, lon = self.to_geo(x, y)
        self.scale = max(self.min_scale() * MIN_SCALE_FACTOR, min(MAX_SCALE, self.scale * factor))
        self.lon0 = lon - (x - self.w / 2) / self.scale
        self.lat0 = lat + (y - self.h / 2) / self.scale
        self.clamp()

    def pan(self, dx, dy):
        self.lon0 -= dx / self.scale
        self.lat0 += dy / self.scale
        self.clamp()

    def center_on(self, lat, lon, min_scale=4.0):
        self.scale = max(self.scale, min_scale)
        self.lat0, self.lon0 = lat, lon
        self.clamp()


class WorldMap(tk.Canvas):
    def __init__(self, master, on_select=None, **kw):
        super().__init__(master, bg=theme.MAP_BG, highlightthickness=1, highlightbackground=theme.PANEL_HIGH, **kw)
        self.rings, self.detailed = load_land()
        self.proj = Projection(800, 400)
        self.items, self.layers, self.selected, self.home = [], {"military", "conflict", "hazard", "news"}, None, None
        self.on_select = on_select
        self._hits = []
        self._drag = None
        self._moved = False
        self.bind("<Configure>", self._resized)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self._zoom(e, 1.25))
        self.bind("<Button-5>", lambda e: self._zoom(e, 0.8))
        self.bind("<Double-Button-1>", lambda e: self._zoom(e, 1.6))

    # ----- public -----
    def set_data(self, items, home=None):
        self.items, self.home = [i for i in items if i.pinned], home
        self.redraw()

    def set_layers(self, layers):
        self.layers = set(layers)
        self.redraw()

    def zoom_by(self, factor):
        self.proj.zoom_at(self.proj.w / 2, self.proj.h / 2, factor)
        self.redraw()

    def reset_view(self):
        self.proj.scale = self.proj.min_scale()
        self.proj.lon0, self.proj.lat0 = 0.0, 15.0
        self.proj.clamp()
        self.redraw()

    def center_on(self, lat, lon):
        self.proj.center_on(lat, lon)
        self.redraw()

    def select(self, item):
        self.selected = item.uid if item else None
        self.redraw()

    @staticmethod
    def layer_of(item):
        return "hazard" if item.kind in ("hazard", "weather", "space", "health") else item.kind

    # ----- drawing -----
    def _resized(self, e):
        self.proj.resize(e.width, e.height)
        self.redraw()

    def redraw(self):
        self.delete("all")
        p = self.proj
        for lon in range(-180, 181, 30):
            x, _ = p.to_px(0, lon)
            self.create_line(x, 0, x, p.h, fill=theme.PANEL, width=1)
        for lat in range(-90, 91, 30):
            _, y = p.to_px(lat, 0)
            self.create_line(0, y, p.w, y, fill=theme.PANEL, width=1)
        for ring in self.rings:
            pts = []
            for lon, lat in ring:
                x, y = p.to_px(lat, lon)
                pts += [x, y]
            xs, ys = pts[0::2], pts[1::2]
            if max(xs) < 0 or min(xs) > p.w or max(ys) < 0 or min(ys) > p.h:
                continue
            self.create_polygon(pts, fill=theme.LAND, outline=theme.OUTLINE, width=1)
        self._hits = []
        for it in self.items:
            if self.layer_of(it) not in self.layers:
                continue
            x, y = p.to_px(it.lat, it.lon)
            if -10 <= x <= p.w + 10 and -10 <= y <= p.h + 10:
                self._pin(it, x, y)
        if self.home:
            x, y = p.to_px(*self.home)
            self.create_oval(x - 14, y - 14, x + 14, y + 14, outline=theme.BLUE, width=2)
            self.create_oval(x - 5, y - 5, x + 5, y + 5, fill=theme.BLUE, outline="")
            self.create_text(x + 20, y - 2, text="HOME", fill=theme.BONE, anchor="w", font=("Segoe UI", 9, "bold"))

    def _pin(self, it, x, y):
        color = theme.KIND_COLORS.get(it.kind, theme.MUTED)
        r = 4 + it.severity
        if it.kind == "military":
            self.create_polygon(x, y - r - 2, x + r + 2, y, x, y + r + 2, x - r - 2, y, fill=color, outline=theme.CHARCOAL)
        else:
            if it.severity >= 2:
                self.create_oval(x - r - 5, y - r - 5, x + r + 5, y + r + 5, fill=color, outline="", stipple="gray25")
            self.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=theme.CHARCOAL)
        if it.uid == self.selected:
            self.create_oval(x - r - 8, y - r - 8, x + r + 8, y + r + 8, outline=theme.BONE, width=2)
        self._hits.append((x, y, it))

    # ----- interaction -----
    def _press(self, e):
        self._drag, self._moved = (e.x, e.y), False

    def _motion(self, e):
        if self._drag:
            dx, dy = e.x - self._drag[0], e.y - self._drag[1]
            if abs(dx) + abs(dy) > 3:
                self._moved = True
            self.proj.pan(dx, dy)
            self._drag = (e.x, e.y)
            self.redraw()

    def _release(self, e):
        if not self._moved:
            self.pick(e.x, e.y)
        self._drag = None

    def pick(self, x, y):
        best, bd = None, 14 ** 2
        for hx, hy, it in self._hits:
            d = (hx - x) ** 2 + (hy - y) ** 2
            if d <= bd:
                best, bd = it, d
        if best is not None:
            self.select(best)
            if self.on_select:
                self.on_select(best)
        return best

    def _wheel(self, e):
        self._zoom(e, 1.25 if e.delta > 0 else 0.8)

    def _zoom(self, e, f):
        self.proj.zoom_at(e.x, e.y, f)
        self.redraw()
