"""The Overwatch window: indicators on top, world map in the middle, feed on the right."""

import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from . import __version__, ai, geo, sources, theme
from .engine import Controller
from .mapview import DEFAULT_LAYERS, WorldMap
from . import tor as _tor, torbrowser, ui_cameras, ui_extra, ui_intel, ui_watchtower
from .model import KIND_LABELS, SEVERITY_WORDS, TRUST_LABELS

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FEED_LIMIT = 80
FEED_CHIPS = [("All", None), ("Military", {"military"}), ("Hazards", {"hazard", "weather", "space", "health"}),
              ("News", {"news", "conflict"}), ("Deployments", "deploy"), ("Home only", "home")]
LAYER_CHIPS = [("Military", "military"), ("Troop movements", "deploy"), ("Conflict", "conflict"), ("Hazards", "hazard"),
               ("Weather", "weather"), ("News", "news"), ("My pins", "mine")]


def default_root():
    return os.path.join(os.path.expanduser("~"), "Downloads", "Cindrix", "Overwatch")


# What the add-feed form asks for: the same four categories the Intel dashboard uses, and the kind each one files under.
FEED_CATEGORIES = [("Military", "military"), ("World news", "news"), ("Cyber", "cyber"), ("Prepper", "prepper"), ("Alerts and weather", "hazard")]


def ago(ts, now):
    if not ts:
        return "never"
    s = max(0, int(now - ts))
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return f"{s // 86400} d ago"


def open_url(url):
    if url and url.lower().startswith(("http://", "https://")):
        webbrowser.open(url)
        return True
    return False


class App:
    def __init__(self, controller=None, splash=True, auto=True, pause=None):
        self.c = controller or Controller(default_root())
        self.root = tk.Tk()
        self.root.title("Cindrix Overwatch")
        self.root.configure(bg=theme.CHARCOAL)
        self.root.geometry("1440x900")
        self.root.minsize(1120, 720)
        try:
            self.root.state("zoomed")          # opens maximized on Windows
        except tk.TclError:
            pass
        self.fullscreen = False
        self.root.bind("<F11>", self._toggle_fullscreen)
        self.root.bind("<Escape>", lambda e: self._toggle_fullscreen(force=False) if self.fullscreen else None)
        self._fonts()
        self._icon()
        self.q = queue.Queue()
        self.worker = None
        self.cancel = threading.Event()
        self.auto = auto
        self.selected = None
        self.feed_filter = FEED_CHIPS[0]
        self.layers = set(DEFAULT_LAYERS)
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self._render_feed())
        self.page = None
        self.splash_win = None
        self.splash_started = time.time()
        self._style()
        self._build()
        self.c.mark_opened()
        self.new_count, self.prev_open = self.c.since_last()
        if splash:
            self._show_splash()
        self.refresh_view()
        self.show_page("war")
        self.root.after(100, self._poll)
        self.root.after(30_000, self._tick)
        if auto:
            self.start_refresh()

    # ----- setup -----
    def _fonts(self):
        fams = set(tkfont.families(self.root))
        head = next((f for f in theme.HEADING_FONTS if f in fams), "TkDefaultFont")
        body = next((f for f in theme.BODY_FONTS if f in fams), "TkDefaultFont")
        self.f_title = (head, 17, "bold")
        self.f_big = (head, 20, "bold")
        self.f_num = (head, 34, "bold")
        self.f_head = (body, 10, "bold")
        self.f_body = (body, 10)
        self.f_small = (body, 9)
        self.f_bold = (body, 10, "bold")

    def _icon(self):
        try:
            self.icon_big = tk.PhotoImage(file=os.path.join(DATA, "icon.png"))
            self.root.iconphoto(True, self.icon_big)
            self.icon_small = tk.PhotoImage(file=os.path.join(DATA, "icon_40.png"))
        except tk.TclError:
            self.icon_small = None
        if sys.platform == "win32":
            try:
                self.root.iconbitmap(os.path.join(DATA, "icon.ico"))
            except tk.TclError:
                pass

    def _style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("Treeview", background=theme.PANEL, fieldbackground=theme.PANEL, foreground=theme.BONE,
                     rowheight=26, borderwidth=0, font=self.f_body)
        st.configure("Treeview.Heading", background=theme.PANEL_HIGH, foreground=theme.BONE, font=self.f_head,
                     borderwidth=0)
        st.map("Treeview", background=[("selected", theme.BLUE_DEEP)], foreground=[("selected", theme.ON_BLUE)])
        st.configure("Vertical.TScrollbar", background=theme.PANEL_HIGH, troughcolor=theme.PANEL,
                     bordercolor=theme.PANEL, arrowcolor=theme.MUTED)
        st.configure("TCombobox", fieldbackground=theme.PANEL_HIGH, background=theme.PANEL_HIGH,
                     foreground=theme.BONE, arrowcolor=theme.BONE)

    def btn(self, parent, text, cmd, primary=False, small=False):
        bg, fg = (theme.BLUE, theme.ON_BLUE) if primary else (theme.PANEL_HIGH, theme.BONE)
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=theme.BLUE_DEEP,
                      activeforeground=theme.ON_BLUE, relief="flat", bd=0, padx=14, pady=5 if small else 7,
                      font=self.f_bold, cursor="hand2")
        return b

    def label(self, parent, text="", font=None, fg=theme.BONE, bg=None, **kw):
        return tk.Label(parent, text=text, font=font or self.f_body, fg=fg,
                        bg=bg or parent.cget("bg"), anchor="w", **kw)

    # ----- layout -----
    def _build(self):
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(1, weight=1)
        top = tk.Frame(r, bg=theme.PANEL)
        top.grid(row=0, column=0, sticky="ew")
        if self.icon_small:
            tk.Label(top, image=self.icon_small, bg=theme.PANEL).pack(side="left", padx=(16, 8), pady=8)
        self.label(top, "CINDRIX OVERWATCH", self.f_title).pack(side="left", padx=(0, 18))
        self.nav = {}
        for key, text in (("war", "War room"), ("intel", "Intel"), ("brief", "Brief"), ("settings", "Settings"), ("watchtower", "Watchtower")):
            b = tk.Button(top, text=text, command=lambda k=key: self.show_page(k), relief="flat", bd=0, padx=14, pady=7,
                          font=self.f_bold, cursor="hand2", bg=theme.PANEL, fg=theme.BONE,
                          activebackground=theme.PANEL_HIGH, activeforeground=theme.BONE)
            b.pack(side="left", padx=2)
            self.nav[key] = b
        self.btn(top, "Refresh now", lambda: self.start_refresh(force=True)).pack(side="right", padx=16, pady=8)
        self.status_top = self.label(top, "", self.f_small, theme.MUTED)
        self.status_top.pack(side="right", padx=8)
        # DEFCON: the Overwatch estimate and the public tracker's reading, on every screen except Settings
        self.defcon_box = tk.Frame(top, bg=theme.PANEL, cursor="hand2")
        self.defcon_box.pack(side="right", padx=8)
        self.defcon_est = tk.Label(self.defcon_box, text="", font=self.f_bold, padx=8, pady=3, bg=theme.PANEL_HIGH, fg=theme.BONE)
        self.defcon_pub = tk.Label(self.defcon_box, text="", font=self.f_bold, padx=8, pady=3, bg=theme.PANEL_HIGH, fg=theme.BONE)
        self.defcon_est.pack(side="left", padx=(0, 4))
        self.defcon_pub.pack(side="left")
        for w in (self.defcon_box, self.defcon_est, self.defcon_pub):
            w.bind("<Button-1>", lambda e: self.show_defcon())
        self.body = tk.Frame(r, bg=theme.CHARCOAL)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)
        self.pages = {k: tk.Frame(self.body, bg=theme.CHARCOAL) for k in ("war", "intel", "brief", "settings", "watchtower")}
        for f in self.pages.values():
            f.grid(row=0, column=0, sticky="nsew")
        self.statusbar = self.label(r, "", self.f_small, theme.MUTED, bg=theme.PANEL)
        self.statusbar.grid(row=2, column=0, sticky="ew", ipady=6, padx=0)
        self._build_war(self.pages["war"])
        self.intel = ui_intel.IntelPage(self, self.pages["intel"])
        self._build_brief(self.pages["brief"])
        self._build_settings(self.pages["settings"])
        self.watchtower = ui_watchtower.WatchtowerPage(self, self.pages["watchtower"])
        self.render_defcon()
        self.apply_watchtower_tab()

    def apply_watchtower_tab(self):
        """Show the Watchtower button only when it is switched on in Settings."""
        b = self.nav["watchtower"]
        if self.c.watchtower_on():
            if not b.winfo_ismapped():
                b.pack(side="left", padx=2)
        else:
            if getattr(self, "page", None) == "watchtower":
                self.show_page("settings")
            b.pack_forget()

    def _toggle_fullscreen(self, event=None, force=None):
        """F11 switches between maximized and true full screen (Escape leaves full screen)."""
        self.fullscreen = (not self.fullscreen) if force is None else force
        self.root.attributes("-fullscreen", self.fullscreen)

    def show_page(self, key):
        if getattr(self, "page", None) == "watchtower" and key != "watchtower":
            self.watchtower.hide()
        self.page = key
        self.pages[key].tkraise()
        if key == "settings":
            self.defcon_box.pack_forget()
        elif not self.defcon_box.winfo_ismapped():
            self.defcon_box.pack(side="right", padx=8)
        for k, b in self.nav.items():
            b.configure(bg=theme.BLUE if k == key else theme.PANEL, fg=theme.ON_BLUE if k == key else theme.BONE)
        if key == "watchtower":
            self.watchtower.show()
        if key == "intel":
            self.intel.show()
        if key == "brief":
            self._render_brief_buttons()
            self._render_brief()
        elif key == "settings":
            self._render_sources()
            ui_cameras.render(self)
            self._render_tor()
            self._render_ai()

    # ----- war room -----
    def _build_war(self, p):
        p.columnconfigure(1, weight=1)
        p.rowconfigure(1, weight=1)
        strip = tk.Frame(p, bg=theme.CHARCOAL)
        strip.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        self.tiles = []
        for i in range(9):
            strip.columnconfigure(i, weight=1, uniform="tile")
            t = tk.Frame(strip, bg=theme.PANEL)
            t.grid(row=0, column=i, sticky="nsew", padx=4)
            bar = tk.Frame(t, bg=theme.GREEN, height=3)
            bar.pack(fill="x")
            name = self.label(t, "", self.f_small, theme.MUTED)
            name.pack(fill="x", padx=10, pady=(6, 0))
            word = self.label(t, "", self.f_big)
            word.pack(fill="x", padx=10)
            note = self.label(t, "", self.f_small, theme.MUTED)
            note.pack(fill="x", padx=10, pady=(0, 6))
            self.tiles.append((bar, name, word, note))
        # left column
        left = tk.Frame(p, bg=theme.CHARCOAL, width=260)
        left.grid(row=1, column=0, sticky="ns", padx=(10, 4), pady=4)
        left.grid_propagate(False)
        card = tk.Frame(left, bg=theme.PANEL)
        card.pack(fill="x", pady=(0, 8))
        self.label(card, "SINCE YOU LAST LOOKED", self.f_small, theme.MUTED).pack(fill="x", padx=14, pady=(10, 0))
        self.new_label = self.label(card, "0", self.f_num, theme.BLUE)
        self.new_label.pack(fill="x", padx=14)
        self.new_sub = self.label(card, "", self.f_small, theme.MUTED)
        self.new_sub.pack(fill="x", padx=14)
        b = self.btn(card, "Open daily brief", lambda: self.show_page("brief"), primary=True, small=True)
        b.pack(fill="x", padx=14, pady=10)
        self.watch = tk.Frame(left, bg=theme.PANEL)
        self.watch.pack(fill="x", pady=(0, 8))
        self.srcbox = tk.Frame(left, bg=theme.PANEL)
        self.srcbox.pack(fill="both", expand=True)
        # centre: map, selection, timeline
        mid = tk.Frame(p, bg=theme.CHARCOAL)
        mid.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        mid.rowconfigure(1, weight=1)
        mid.columnconfigure(0, weight=1)
        bar = tk.Frame(mid, bg=theme.CHARCOAL)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.layer_btns = {}
        for text, key in LAYER_CHIPS:
            b = tk.Button(bar, text=text, command=lambda k=key: self._toggle_layer(k), relief="flat", bd=0, padx=12,
                          pady=4, font=self.f_bold, cursor="hand2")
            b.pack(side="left", padx=(0, 6))
            self.layer_btns[key] = b
        for text, cmd in (("Reset view", lambda: self.map.reset_view()), ("Center on home", self._center_home),
                          ("−", lambda: self.map.zoom_by(0.8)), ("+", lambda: self.map.zoom_by(1.25))):
            tk.Button(bar, text=text, command=cmd, relief="flat", bd=0, padx=12, pady=4, font=self.f_bold,
                      bg=theme.PANEL_HIGH, fg=theme.BONE, cursor="hand2").pack(side="right", padx=(6, 0))
        self.map = WorldMap(mid, on_select=self.select)
        self.map.grid(row=1, column=0, sticky="nsew")
        self.sel = tk.Frame(mid, bg=theme.PANEL, height=104)
        self.sel.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.sel.grid_propagate(False)
        self.sel_kind = self.label(self.sel, "", self.f_small, theme.MUTED)
        self.sel_kind.place(x=14, y=8)
        self.sel_title = tk.Label(self.sel, text="Click a pin or a feed item to see it here", font=self.f_bold,
                                  fg=theme.BONE, bg=theme.PANEL, anchor="w", justify="left", wraplength=640)
        self.sel_title.place(x=14, y=28)
        self.sel_meta = self.label(self.sel, "", self.f_small, theme.MUTED)
        self.sel_meta.place(x=14, y=78)
        self.sel_open = self.btn(self.sel, "Open page", self._open_selected, primary=True, small=True)
        self.sel_open.place(relx=1.0, x=-14, y=10, anchor="ne")
        self.sel_open.place_forget()
        self.sel_tr = self.btn(self.sel, "Translate", self._translate_selected, small=True)
        self.sel_tr.place(relx=1.0, x=-14, y=48, anchor="ne")
        self.sel_tr.place_forget()
        self.sel_note = self.label(self.sel, "", self.f_small, theme.MUTED)
        self.sel_note.place(relx=1.0, x=-14, y=82, anchor="ne")
        self.show_original = False
        self.timeline = tk.Canvas(mid, bg=theme.PANEL, height=64, highlightthickness=0)
        self.timeline.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.timeline.bind("<Configure>", lambda e: self._render_timeline())
        # right: feed
        right = tk.Frame(p, bg=theme.PANEL, width=392)
        right.grid(row=1, column=2, sticky="ns", padx=(4, 10), pady=4)
        right.grid_propagate(False)
        chips = tk.Frame(right, bg=theme.PANEL)
        chips.pack(fill="x", padx=10, pady=(10, 4))
        self.chip_btns = []
        for chip in FEED_CHIPS:
            b = tk.Button(chips, text=chip[0], command=lambda c=chip: self._set_filter(c), relief="flat", bd=0, padx=10,
                          pady=4, font=self.f_bold, cursor="hand2")
            b.pack(side="left", padx=(0, 4))
            self.chip_btns.append((chip, b))
        e = tk.Entry(right, textvariable=self.search, bg=theme.CHARCOAL, fg=theme.BONE, insertbackground=theme.BONE,
                     relief="flat", font=self.f_body, highlightthickness=1, highlightbackground=theme.OUTLINE,
                     highlightcolor=theme.BLUE)
        e.pack(fill="x", padx=10, pady=(2, 6), ipady=5)
        self.feed_canvas = tk.Canvas(right, bg=theme.PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(right, orient="vertical", command=self.feed_canvas.yview)
        self.feed_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.feed_canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.feed_inner = tk.Frame(self.feed_canvas, bg=theme.PANEL)
        self._feed_win = self.feed_canvas.create_window(0, 0, window=self.feed_inner, anchor="nw")
        self.feed_inner.bind("<Configure>", lambda e: self.feed_canvas.configure(scrollregion=self.feed_canvas.bbox("all")))
        self.feed_canvas.bind("<Configure>", lambda e: self.feed_canvas.itemconfigure(self._feed_win, width=e.width))
        self.feed_canvas.bind("<Enter>", lambda e: self.feed_canvas.bind_all("<MouseWheel>", self._feed_wheel))
        self.feed_canvas.bind("<Leave>", lambda e: self.feed_canvas.unbind_all("<MouseWheel>"))

    def _feed_wheel(self, e):
        self.feed_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def _set_filter(self, chip):
        self.feed_filter = chip
        self._render_feed()

    def _toggle_layer(self, key):
        (self.layers.discard if key in self.layers else self.layers.add)(key)
        self.map.set_layers(self.layers)
        self._style_chips()

    def _center_home(self):
        hp = geo.home_point(self.c.settings["home_states"])
        if hp:
            self.map.center_on(*hp)

    def _style_chips(self):
        for key, b in self.layer_btns.items():
            on = key in self.layers
            b.configure(bg=theme.BLUE if on else theme.PANEL_HIGH, fg=theme.ON_BLUE if on else theme.MUTED)
        for chip, b in self.chip_btns:
            on = chip == self.feed_filter
            b.configure(bg=theme.BLUE if on else theme.PANEL, fg=theme.ON_BLUE if on else theme.BONE)

    # ----- rendering the war room -----
    def render_defcon(self):
        d = self.c.defcon()
        e = d["estimate"]
        self.defcon_est.configure(text=f"DEFCON {e['level']}  Overwatch est.", bg=theme.DEFCON_COLORS[e["level"]], fg=theme.ON_BLUE)
        p = d["public"]
        if p:
            self.defcon_pub.configure(text=f"DEFCON {p['level']}  Public" + ("  (old)" if p["old"] else ""),
                                      bg=theme.DEFCON_COLORS[p["level"]] if not p["old"] else theme.PANEL_HIGH,
                                      fg=theme.ON_BLUE if not p["old"] else theme.BONE)
        else:
            self.defcon_pub.configure(text="Public: not read yet", bg=theme.PANEL_HIGH, fg=theme.MUTED)

    def show_defcon_guide(self):
        """A short pop-up: each DEFCON level and what it means."""
        from . import defcon
        w = tk.Toplevel(self.root)
        w.title("What the DEFCON levels mean")
        w.configure(bg=theme.CHARCOAL)
        w.transient(self.root)
        w.geometry("640x520")
        self.label(w, "DEFCON levels", self.f_big, bg=theme.CHARCOAL).pack(anchor="w", padx=18, pady=(14, 2))
        self.label(w, defcon.GUIDE_INTRO, self.f_small, theme.MUTED, bg=theme.CHARCOAL, wraplength=600, justify="left").pack(anchor="w", padx=18)
        for lvl, name, means, ready in defcon.LEVELS:
            row = tk.Frame(w, bg=theme.PANEL)
            row.pack(fill="x", padx=18, pady=(8, 0))
            tk.Label(row, text=f"DEFCON {lvl}", font=self.f_bold, fg=theme.ON_BLUE, bg=theme.DEFCON_COLORS[lvl], width=10, pady=6).pack(side="left", padx=8, pady=8)
            col = tk.Frame(row, bg=theme.PANEL)
            col.pack(side="left", fill="x", expand=True, pady=6)
            self.label(col, f"{means}  ({name.title()})", self.f_bold, bg=theme.PANEL, wraplength=480, justify="left").pack(anchor="w")
            self.label(col, ready, self.f_small, theme.MUTED, bg=theme.PANEL, wraplength=480, justify="left").pack(anchor="w")
        self.label(w, defcon.GUIDE_NOTE, self.f_small, theme.AMBER, bg=theme.CHARCOAL, wraplength=600, justify="left").pack(anchor="w", padx=18, pady=(14, 6))
        self.btn(w, "Close", w.destroy, small=True).pack(anchor="e", padx=18, pady=6)

    def show_defcon(self):
        from . import defcon
        d = self.c.defcon()
        e, p = d["estimate"], d["public"]
        w = tk.Toplevel(self.root)
        w.title("DEFCON")
        w.configure(bg=theme.CHARCOAL)
        w.transient(self.root)
        w.geometry("560x430")
        self.label(w, f"Overwatch estimate: DEFCON {e['level']}", self.f_big, theme.DEFCON_COLORS[e["level"]], bg=theme.CHARCOAL).pack(anchor="w", padx=18, pady=(16, 0))
        self.label(w, defcon.WORDS[e["level"]], self.f_small, theme.MUTED, bg=theme.CHARCOAL).pack(anchor="w", padx=18)
        self.label(w, "Worked out from the status lights, so it follows how much is being reported:", self.f_small, bg=theme.CHARCOAL).pack(anchor="w", padx=18, pady=(8, 2))
        for r in e["reasons"]:
            self.label(w, "  \u2022 " + r, self.f_small, theme.MUTED, bg=theme.CHARCOAL).pack(anchor="w", padx=18)
        if p:
            when = time.strftime("%b %d %H:%M", time.localtime(p["fetched"]))
            self.label(w, f"Public tracker: DEFCON {p['level']}", self.f_big, theme.DEFCON_COLORS[p["level"]], bg=theme.CHARCOAL).pack(anchor="w", padx=18, pady=(18, 0))
            self.label(w, f"defconlevel.com, its update: {p['updated'] or 'not stated'}. Read by Overwatch {when}."
                       + (" This reading is more than six hours old." if p["old"] else ""), self.f_small, theme.MUTED, bg=theme.CHARCOAL).pack(anchor="w", padx=18)
        else:
            self.label(w, "Public tracker: not read yet (needs the internet; it is read on each refresh).", self.f_small, theme.MUTED, bg=theme.CHARCOAL).pack(anchor="w", padx=18, pady=(18, 0))
        self.label(w, "Neither number is official. The real DEFCON level is not published. The estimate is Overwatch's own reading of the news it "
                   "collected; the tracker is another site's estimate. Do not treat either as a prediction.", self.f_small, theme.AMBER, bg=theme.CHARCOAL,
                   wraplength=520, justify="left").pack(anchor="w", padx=18, pady=(18, 8))
        self.btn(w, "Close", w.destroy, small=True).pack(anchor="e", padx=18, pady=8)

    def refresh_view(self):
        self.render_defcon()
        now = self.c.now()
        for (bar, name, word, note), (iid, label, lvl, w, n) in zip(self.tiles, self.c.indicators()):
            col = theme.LEVEL_COLORS[lvl]
            bar.configure(bg=col)
            name.configure(text=label.upper())
            word.configure(text=w, fg=col)
            note.configure(text=n)
        items = self.c.feed(limit=400)
        self.map.set_data(items, geo.home_point(self.c.settings["home_states"]))
        if self.page == "intel":
            self.intel.render()
        self._render_feed()
        self._render_watch()
        self._render_timeline()
        self._style_chips()
        self.new_label.configure(text=str(self.new_count))
        self.new_sub.configure(text=("Last opened " + ago(self.prev_open, now)) if self.prev_open
                               else "First time opening")
        self._status()

    def _render_feed(self):
        for w in self.feed_inner.winfo_children():
            w.destroy()
        kinds = self.feed_filter[1]
        home = kinds == "home"
        deploy = kinds == "deploy"
        items = self.c.feed(kinds=None if home or deploy or kinds is None else kinds, home_only=home, text=self.search.get(),
                            limit=FEED_LIMIT, deploy_only=deploy)
        self.feed_items = items
        if not items:
            self.label(self.feed_inner, "Nothing here yet. Press Refresh now while online.\nSaved items show even offline.",
                       self.f_small, theme.MUTED, justify="left").pack(fill="x", padx=8, pady=12)
        for it in items:
            self._card(it)
        self.feed_canvas.yview_moveto(0)
        self._style_chips()

    def _card(self, it):
        col = theme.KIND_COLORS.get(it.kind, theme.MUTED)
        outer = tk.Frame(self.feed_inner, bg=theme.PANEL_HIGH, cursor="hand2")
        outer.pack(fill="x", pady=3, padx=(0, 8))
        stripe = tk.Frame(outer, bg=col, width=4)
        stripe.pack(side="left", fill="y")
        box = tk.Frame(outer, bg=theme.PANEL_HIGH)
        box.pack(side="left", fill="both", expand=True, padx=8, pady=6)
        meta = tk.Frame(box, bg=theme.PANEL_HIGH)
        meta.pack(fill="x")
        parts = [(KIND_LABELS[it.kind], col)]
        if it.first_seen > self.prev_open and self.prev_open:
            parts.append(("NEW", theme.BLUE))
        if set(it.states) & set(self.c.settings["home_states"]):
            parts.append(("HOME", theme.BLUE))
        if it.title_en:
            parts.append(("TRANSLATED", theme.MUTED))
        for text, c in parts:
            tk.Label(meta, text=text, font=self.f_small, fg=c, bg=theme.PANEL_HIGH).pack(side="left", padx=(0, 6))
        tk.Label(meta, text=f"{it.source}  ·  {ago(it.ts, self.c.now())}", font=self.f_small, fg=theme.MUTED,
                 bg=theme.PANEL_HIGH).pack(side="left")
        tk.Label(box, text=it.shown, font=self.f_bold, fg=theme.BONE, bg=theme.PANEL_HIGH, anchor="w", justify="left",
                 wraplength=300).pack(fill="x")
        sub = TRUST_LABELS[it.trust] + (f", {it.count} sources" if it.count > 1 else "")
        tk.Label(box, text=sub, font=self.f_small, fg=theme.MUTED, bg=theme.PANEL_HIGH, anchor="w").pack(fill="x")

        def bind(w):
            w.bind("<Button-1>", lambda e, i=it: self.select(i, from_feed=True))
            w.bind("<Double-Button-1>", lambda e, i=it: self.open_link(i.url))
            for ch in w.winfo_children():
                bind(ch)
        bind(outer)

    def _render_watch(self):
        for w in self.watch.winfo_children():
            w.destroy()
        self.label(self.watch, "WATCHLISTS", self.f_small, theme.MUTED).pack(fill="x", padx=14, pady=(10, 4))
        items = self.c.feed(hours=24, limit=1000)
        for st in self.c.settings["home_states"]:
            n = sum(1 for i in items if st in i.states)
            self._count_row(self.watch, f"Home: {geo.STATES[st][0]}", n, theme.BLUE)
        for text, kinds, col in (("Conflict", {"conflict"}, theme.RED), ("Military", {"military"}, theme.BLUE),
                                 ("Hazards and weather", {"hazard", "weather"}, theme.AMBER),
                                 ("Health", {"health"}, theme.ORANGE), ("Space weather", {"space"}, theme.AMBER)):
            self._count_row(self.watch, text, sum(1 for i in items if i.kind in kinds), col)
        tk.Frame(self.watch, height=8, bg=theme.PANEL).pack()
        for w in self.srcbox.winfo_children():
            w.destroy()
        self.label(self.srcbox, "MILITARY SOURCES", self.f_small, theme.MUTED).pack(fill="x", padx=14, pady=(10, 4))
        for row in self.c.source_status():
            if row["group"] != "Military":
                continue
            h = row["health"]
            col = theme.MUTED if not h else theme.GREEN if h["ok"] else theme.RED
            f = tk.Frame(self.srcbox, bg=theme.PANEL)
            f.pack(fill="x", padx=14, pady=1)
            tk.Label(f, text="●", fg=col, bg=theme.PANEL, font=self.f_small).pack(side="left")
            tk.Label(f, text=row["name"], fg=theme.BONE, bg=theme.PANEL, font=self.f_small, anchor="w").pack(side="left", padx=6)
            state = "not checked" if not h else (f"{h['count']} items" if h["ok"] else "unreachable")
            tk.Label(f, text=state, fg=theme.MUTED, bg=theme.PANEL, font=self.f_small).pack(side="right")

    def _count_row(self, parent, text, n, color):
        f = tk.Frame(parent, bg=theme.PANEL)
        f.pack(fill="x", padx=14, pady=1)
        tk.Label(f, text="●", fg=color, bg=theme.PANEL, font=self.f_small).pack(side="left")
        tk.Label(f, text=text, fg=theme.BONE, bg=theme.PANEL, font=self.f_body, anchor="w").pack(side="left", padx=6)
        tk.Label(f, text=str(n), fg=theme.BONE, bg=theme.PANEL_HIGH, font=self.f_small, padx=8).pack(side="right")

    def _render_timeline(self):
        cv = self.timeline
        cv.delete("all")
        w, h = max(cv.winfo_width(), 100), max(cv.winfo_height(), 40)
        now = self.c.now()
        buckets = [0] * 24
        for it in self.c.all_items(24):
            idx = 23 - int((now - it.ts) // 3600)
            if 0 <= idx < 24:
                buckets[idx] += 1
        peak = max(buckets) or 1
        cv.create_text(10, 8, text="LAST 24 HOURS, ITEMS PER HOUR", anchor="w", fill=theme.MUTED, font=self.f_small)
        bw = (w - 20) / 24
        for i, n in enumerate(buckets):
            bh = 4 + (h - 34) * n / peak
            x0 = 10 + i * bw
            cv.create_rectangle(x0 + 1, h - 6 - bh, x0 + bw - 1, h - 6, outline="",
                                fill=theme.BLUE if i >= 18 else theme.OUTLINE)

    # ----- selection -----
    def select(self, item, from_feed=False):
        self.selected = item
        self.show_original = False
        self.sel_note.configure(text="")
        self.sel_kind.configure(text=KIND_LABELS[item.kind] + ("  ·  " + SEVERITY_WORDS[item.severity]),
                                fg=theme.KIND_COLORS.get(item.kind, theme.MUTED))
        self._show_sel_title()
        more = f"  ·  {item.count} sources" if item.count > 1 else ""
        place = f"  ·  {item.place}" if item.place else ""
        self.sel_meta.configure(text=f"{item.source}  ·  {TRUST_LABELS[item.trust]}{more}{place}  ·  "
                                     f"{ago(item.ts, self.c.now())}")
        if item.url:
            self.sel_open.place(relx=1.0, x=-14, y=10, anchor="ne")
        else:
            self.sel_open.place_forget()
        self.sel_tr.place(relx=1.0, x=-14, y=48, anchor="ne")
        self._label_translate_button()
        self.map.select(item)
        if from_feed and item.pinned:
            self.map.center_on(item.lat, item.lon)

    def _show_sel_title(self):
        it = self.selected
        if not it:
            return
        text = it.title if self.show_original else it.shown
        if it.summary_en and not self.show_original:
            text += "\n" + it.summary_en[:160]
        self.sel_title.configure(text=text)

    def _label_translate_button(self):
        it = self.selected
        if it and it.title_en:
            self.sel_tr.configure(text="Show original" if not self.show_original else "Show English")
        else:
            self.sel_tr.configure(text="Translate")

    def _translate_selected(self):
        it = self.selected
        if not it:
            return
        if it.title_en:                                   # already translated: flip between the two texts
            self.show_original = not self.show_original
            self._show_sel_title()
            self._label_translate_button()
            return
        from . import lang
        if not lang.looks_foreign(it.title):
            self.sel_note.configure(text="This looks like English already.", fg=theme.MUTED)
            return
        if not self.c.ai.translator_ready():
            self.sel_note.configure(text="Pick the Cindrix folder in Settings > AI first.", fg=theme.AMBER)
            return
        self.sel_tr.configure(state="disabled")
        self.sel_note.configure(text="Translating...", fg=theme.MUTED)

        def say(m):
            self.root.after(0, lambda: self.sel_note.configure(text=m))

        def done(kind, val):
            self.sel_tr.configure(state="normal")
            if kind == "err":
                self.sel_note.configure(text=str(val), fg=theme.RED)
                return
            self.sel_note.configure(text="Translated by the AI on this PC. The original is kept.", fg=theme.MUTED)
            if self.selected is it:
                self.show_original = False
                self._show_sel_title()
                self._label_translate_button()
            self.refresh_view()
        ui_extra.Worker(self.root, lambda: self.c.ai.translate_item(it, say), done)

    def _auto_translate(self):
        """After a refresh: translate new non-English headlines in the background, then redraw."""
        if getattr(self, "_translating", False) or not self.c.settings.get("auto_translate", True):
            return
        if not self.c.ai.translator_ready():
            return
        self._translating = True

        def run():
            n = 0
            try:
                n = self.c.ai.auto_translate(lambda m: self.q.put(("p", m)))
            except Exception:
                pass
            self._translating = False
            self.q.put(("tr", n))
        threading.Thread(target=run, daemon=True).start()

    def _auto_pin(self):
        """After a refresh: with the AI on, place unpinned stories on the map (the model names the place, the list gives the spot)."""
        if getattr(self, "_pinning", False) or not self.c.settings.get("ai_enabled", False) or not self.c.settings.get("ai_pins", True):
            return
        self._pinning = True

        def run():
            n = 0
            try:
                n = self.c.ai.auto_pin(lambda m: self.q.put(("p", m)))
            except Exception:
                pass
            self._pinning = False
            self.q.put(("tr", n))      # same redraw path as translations
        threading.Thread(target=run, daemon=True).start()

    def begin_pin(self, item, done):
        """Pin mode: the next click on the map places this story there. The pin is yours and stays until you remove it."""
        self.show_page("war")
        self.status_top.configure(text="Click the map where this story belongs", fg=theme.AMBER)

        def placed(lat, lon):
            self.status_top.configure(text="", fg=theme.MUTED)
            try:
                self.c.pin_item(item.uid, lat, lon)
            except ValueError:
                return
            done("")
        self.map.set_pin_mode(placed)

    def _open_selected(self):
        if self.selected:
            self.open_link(self.selected.url)

    # ----- brief, sources, settings -----
    def _build_brief(self, p):
        p.rowconfigure(1, weight=1)
        p.columnconfigure(0, weight=1)
        bar = tk.Frame(p, bg=theme.CHARCOAL)
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        self.btn(bar, "Copy brief", self._copy_brief, primary=True).pack(side="left")
        self.btn(bar, "Save brief to a file", self._save_brief).pack(side="left", padx=8)
        self.ai_text = ""
        self.ai_brief_btn = self.btn(bar, "Write the brief with AI", self._write_ai_brief)
        self.ai_brief_btn.pack(side="left", padx=8)
        self.brief_note = self.label(bar, "", self.f_small, theme.MUTED)
        self.brief_note.configure(wraplength=1000, justify="left")
        self.brief_note.pack(side="left", padx=10)
        self.brief_text = tk.Text(p, bg=theme.PANEL, fg=theme.BONE, font=self.f_body, relief="flat", wrap="word",
                                  padx=16, pady=12, insertbackground=theme.BONE)
        self.brief_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

    def _render_brief(self):
        self.brief_text.configure(state="normal")
        self.brief_text.delete("1.0", "end")
        self.brief_text.insert("1.0", self._full_brief())
        self.brief_text.configure(state="disabled")
        self._render_brief_buttons()

    def _full_brief(self):
        plain = self.c.brief()
        return (self.ai_text + "\n\n" + "=" * 60 + "\n\n" + plain) if self.ai_text else plain

    def _copy_brief(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self._full_brief())
        self.brief_note.configure(text="Copied.")

    def _save_brief(self):
        path = os.path.join(self.c.root, time.strftime("brief-%Y-%m-%d.txt", time.localtime(self.c.now())))
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._full_brief())
        self.brief_note.configure(text="Saved to " + path)

    def _build_sources(self, p):
        p.rowconfigure(2, weight=1)
        p.columnconfigure(0, weight=1)
        bar = tk.Frame(p, bg=theme.CHARCOAL)
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        self.btn(bar, "Check all sources now", lambda: self.start_refresh(force=True), primary=True).pack(side="left")
        self.btn(bar, "Export source list", self._export_sources).pack(side="left", padx=8)
        self.btn(bar, "Assistant: find and connect a feed", lambda: ui_extra.FeedAssistant(self, self.cf_url.get().strip()),
                 primary=True).pack(side="left", padx=8)
        # add a feed: it appears in the list below with its own switch
        add = tk.Frame(p, bg=theme.PANEL)
        add.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.label(add, "Add your own feed or website (https only; .onion works when Tor is running). A site with no feed is read for its article links. It gets its own on/off switch below.",
                   self.f_bold).grid(row=0, column=0, columnspan=8, sticky="w", padx=12, pady=(10, 4))
        self.cf_name, self.cf_url = tk.StringVar(), tk.StringVar()
        self.cf_cat = tk.StringVar(value=FEED_CATEGORIES[1][0])
        for i, (text, var, wd) in enumerate((("Name", self.cf_name, 20), ("Address", self.cf_url, 50))):
            self.label(add, text, self.f_small, theme.MUTED).grid(row=1, column=i * 2, sticky="w", padx=(12, 4))
            tk.Entry(add, textvariable=var, width=wd, bg=theme.CHARCOAL, fg=theme.BONE, insertbackground=theme.BONE,
                     relief="flat").grid(row=1, column=i * 2 + 1, sticky="w", ipady=4)
        self.label(add, "Category", self.f_small, theme.MUTED).grid(row=1, column=4, sticky="w", padx=(12, 4))
        ttk.Combobox(add, textvariable=self.cf_cat, values=[c for c, _ in FEED_CATEGORIES], width=18,
                     state="readonly").grid(row=1, column=5, padx=4)
        self.btn(add, "Add feed", self._add_feed, small=True).grid(row=1, column=6, padx=8)
        self.src_note = self.label(add, "", self.f_small, theme.MUTED)
        self.src_note.grid(row=2, column=0, columnspan=8, sticky="w", padx=12, pady=(4, 10))
        # the list of every feed, each with a switch
        box = tk.Frame(p, bg=theme.CHARCOAL)
        box.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 10))
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.feed_canvas2 = cv = tk.Canvas(box, bg=theme.CHARCOAL, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        cv.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.feed_list = tk.Frame(cv, bg=theme.CHARCOAL)
        win = cv.create_window(0, 0, window=self.feed_list, anchor="nw")
        self.feed_list.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", lambda ev: cv.yview_scroll(-1 if ev.delta > 0 else 1, "units")))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        self.feed_rows = {}

    def _render_sources(self):
        cv = self.feed_canvas2
        top = cv.yview()[0]
        for w in self.feed_list.winfo_children():
            w.destroy()
        self.feed_rows = {}
        now = self.c.now()
        disabled = set(self.c.settings["disabled"])
        groups = {}
        for row in self.c.source_status():
            groups.setdefault(row["group"], []).append(row)
        for group, rows in groups.items():
            self.label(self.feed_list, group.upper(), self.f_small, theme.MUTED).pack(fill="x", padx=4, pady=(10, 2))
            for row in rows:
                self._feed_row(row, row["id"] not in disabled, now)
        self.src_note.configure(text=f"{len(disabled)} source(s) turned off." if disabled else "", fg=theme.MUTED)
        cv.update_idletasks()
        cv.yview_moveto(top)

    def _feed_row(self, row, on, now):
        h = row["health"]
        status = "not checked yet" if not h else (f"working, {h['count']} items, {ago(h['last_ok'], now)}" if h["ok"]
                                                  else "problem: " + (h["error"] or "failed"))
        if not on:
            status = "turned off"
        fr = tk.Frame(self.feed_list, bg=theme.PANEL)
        fr.pack(fill="x", pady=2)
        sid = row["id"]
        sw = tk.Label(fr, text="ON " if on else " OFF", font=self.f_bold, width=5, cursor="hand2",
                      bg=theme.BLUE if on else theme.PANEL_HIGH, fg=theme.ON_BLUE if on else theme.MUTED)
        sw.pack(side="left", padx=10, pady=8)
        sw.bind("<Button-1>", lambda e, i=sid, now_on=on: self._flip_source(i, not now_on))
        info = tk.Frame(fr, bg=theme.PANEL)
        info.pack(side="left", fill="x", expand=True, pady=4)
        tk.Label(info, text=row["name"], font=self.f_bold, fg=theme.BONE if on else theme.MUTED, bg=theme.PANEL, anchor="w").pack(fill="x")
        bad = h and not h["ok"] and on
        cat = next((n for _, n, ks in sources.INTEL_CHANNELS if row["kind"] in ks), "")
        tk.Label(info, text=f"{cat}  \u00b7  {TRUST_LABELS[row['trust']]}  \u00b7  {status}", font=self.f_small, fg=theme.RED if bad else theme.MUTED,
                 bg=theme.PANEL, anchor="w").pack(fill="x")
        if sid.startswith("custom-"):
            rm = tk.Label(fr, text="Remove", font=self.f_small, fg=theme.BLUE, bg=theme.PANEL, cursor="hand2")
            rm.pack(side="right", padx=12)
            rm.bind("<Button-1>", lambda e, i=int(sid.split("-")[1]): self._remove_feed(i))
        self.feed_rows[sid] = sw

    def _flip_source(self, sid, enable):
        self.c.set_source_enabled(sid, enable)
        self._render_sources()

    def _render_ai(self):
        st = self.c.ai.status()
        lines = [st["message"]]
        if st["base"]:
            lines.append(f"Folder: {st['base']}")
            lines.append(f"Engine: {st['engine'] or 'not found'}")
            lines.append(f"Chat model: {st['chat'] or 'none found'}   Translation model: {st['mt'] or 'none found'}")
            lines.append("The model is running now." if st["running"] else "The model starts when you ask for an AI brief and stops when Overwatch closes.")
        self.ai_status.configure(text="\n".join(lines))

    def _save_ai(self):
        self.c.settings["ai_root"] = self.ai_root_var.get().strip()
        self.c.settings["ai_enabled"] = bool(self.ai_enabled_var.get())
        self.c.settings["ai_engine"] = self.ai_engine_var.get().strip()
        self.c.settings["ai_model"] = self.ai_model_var.get()
        self.c.settings["auto_translate"] = bool(self.ai_auto_var.get())
        self.c.settings["ai_focus"] = bool(self.ai_focus_var.get())
        self.c.save_settings()
        self._render_ai()
        self._render_brief_buttons()

    def _save_instructions(self):
        text = self.ai_instr.get("1.0", "end").strip()
        self.c.settings["ai_instructions"] = "" if text == ai.DEFAULT_INSTRUCTIONS else text
        self.c.save_settings()
        self.ai_instr_note.configure(text="Saved. The next AI brief follows these.", fg=theme.GREEN)

    def _reset_instructions(self):
        self.ai_instr.delete("1.0", "end")
        self.ai_instr.insert("1.0", ai.DEFAULT_INSTRUCTIONS)
        self._save_instructions()
        self.ai_instr_note.configure(text="Back to the built-in instructions.", fg=theme.GREEN)

    def _render_brief_buttons(self):
        ok = self.c.settings.get("ai_enabled") and self.c.ai.status()["message"] == "Ready to use."
        self.ai_brief_btn.configure(state="normal" if ok else "disabled")
        if not ok:
            st = self.c.ai.status()
            why = ("AI brief is off. Turn it on in Settings > AI." if not self.c.settings.get("ai_enabled")
                   else "AI is on but not ready: " + st["message"])
            self.brief_note.configure(text=why, fg=theme.AMBER if self.c.settings.get("ai_enabled") else theme.MUTED)
        elif self.brief_note.cget("text").startswith(("AI brief is off", "AI is on but")):
            self.brief_note.configure(text="Ready. Press the button to write the AI brief.", fg=theme.MUTED)

    def _write_ai_brief(self):
        self.ai_brief_btn.configure(state="disabled")
        self.brief_note.configure(text="Starting...", fg=theme.MUTED)

        def say(m):
            self.root.after(0, lambda: self.brief_note.configure(text=m))

        def done(kind, val):
            self.ai_brief_btn.configure(state="normal")
            if kind == "err":
                self.brief_note.configure(text=val, fg=theme.RED)
                return
            self.ai_text = val
            self.brief_note.configure(text="Done. The plain brief is below the AI one.", fg=theme.GREEN)
            self._render_brief()
        ui_extra.Worker(self.root, lambda: self.c.ai.write_brief(say), done)

    def _tor_poll(self):
        if self.page == "settings":
            self._render_tor()
        self.root.after(1500, self._tor_poll)

    def _render_tor(self):
        self.tor_status.configure(text=self.c.tor.describe())
        sel = self.onion_tree.selection()
        self.onion_tree.delete(*self.onion_tree.get_children())
        for o in self.c.outlets():
            self.onion_tree.insert("", "end", iid=o["name"], text=o["name"],
                                   values=(o["home"], o["onion"] or "(none: paste one below)", o["origin"]))
        if sel and self.onion_tree.exists(sel[0]):
            self.onion_tree.selection_set(sel[0])

    def _picked_outlet(self):
        sel = self.onion_tree.selection()
        if not sel:
            self.tor_note.configure(text="Pick an outlet in the list first.", fg=theme.AMBER)
            return None
        for o in self.c.outlets():
            if o["name"] == sel[0]:
                return o["name"], o["home"] or o["onion"], o["kind"]
        return None

    def _onion_selected(self, event=None):
        sel = self.onion_tree.selection()
        if sel:
            self.onion_var.set(next((o["onion"] for o in self.c.outlets() if o["name"] == sel[0]), ""))

    def _save_onion(self):
        o = self._picked_outlet()
        if not o:
            return
        try:
            saved = self.c.set_onion_address(o[0], self.onion_var.get())
        except ValueError as e:
            self.tor_note.configure(text=str(e), fg=theme.RED)
            return
        self.onion_var.set(saved)
        self.tor_note.configure(text="Saved. Use Connect its feed (via Tor) when Tor is running." if saved else "Cleared.",
                                fg=theme.GREEN)
        self._render_tor()

    def _add_outlet(self):
        try:
            self.c.add_outlet(self.new_name.get(), self.new_home.get(), self.new_onion.get())
        except ValueError as e:
            self.tor_note.configure(text=str(e), fg=theme.RED)
            return
        for v in (self.new_name, self.new_home, self.new_onion):
            v.set("")
        self.tor_note.configure(text="Added to the list. Pick it and use Connect its feed.", fg=theme.GREEN)
        self._render_tor()

    def _remove_outlet(self):
        o = self._picked_outlet()
        if not o:
            return
        if not any(x["name"] == o[0] and x["custom"] for x in self.c.outlets()):
            self.tor_note.configure(text="Only sites you added can be removed. Built-in ones can be left alone.", fg=theme.AMBER)
            return
        self.c.remove_outlet(o[0])
        self._render_tor()

    def _clear_onion(self):
        self.onion_var.set("")
        self._save_onion()

    def _lookup_onion(self):
        o = self._picked_outlet()
        if not o:
            return
        name, home, _ = o
        self.tor_note.configure(text=f"Asking {home} for its onion address...", fg=theme.MUTED)

        def done(kind, val):
            if kind == "err" or not val:
                self.tor_note.configure(text="That site did not hand out an onion address (most do not to automatic readers). "
                                             "Paste one from the outlet's own page in the box below.", fg=theme.AMBER)
                return
            self.c.set_onion_address(name, val)
            self.tor_note.configure(text="Found it in the site's own Onion-Location header.", fg=theme.GREEN)
            self._render_tor()
        ui_extra.Worker(self.root, lambda: self.c.onion_location(home), done)

    def _outlet_feed(self, via_tor):
        o = self._picked_outlet()
        if not o:
            return
        name, home, _ = o
        addr = next((o["onion"] for o in self.c.outlets() if o["name"] == name), "") if via_tor else home
        if via_tor and not addr:
            self.tor_note.configure(text="Paste its onion address in the box below first, then Save address.", fg=theme.AMBER)
            return
        ui_extra.FeedAssistant(self, addr)

    def _outlet_reader(self):
        o = self._picked_outlet()
        if o:
            ui_extra.ReaderWindow(self, next((x["onion"] for x in self.c.outlets() if x["name"] == o[0]), "") or o[1])

    def _open_tor_browser(self, url=""):
        if not ui_extra.open_tor_browser(url, self.c.root):
            bad = torbrowser.problem(self.c.root) if torbrowser.firefox_path(self.c.root) else ""
            self.tor_note.configure(text=bad or "Tor Browser is not installed yet. Press Install Tor Browser (one click).",
                                    fg=theme.AMBER)

    def _install_tor_browser(self):
        self.tor_note.configure(text="Working...", fg=theme.MUTED)

        def done(kind, val):
            self.tor_note.configure(text=val if kind == "err" else "Tor Browser is installed. Press Open Tor Browser.",
                                    fg=theme.RED if kind == "err" else theme.GREEN)

        def work():
            return torbrowser.install(self.c.root, lambda m: self.root.after(0, lambda: self.tor_note.configure(text=m)))
        ui_extra.Worker(self.root, work, done)

    def _export_sources(self):
        path = self.c.export_sources()
        self.src_note.configure(text="Saved the source list to " + path, fg=theme.GREEN)

    def open_link(self, url):
        """Onion links open in the reader; everything else in the normal browser."""
        if _tor.is_onion_url(url):
            if not ui_extra.open_tor_browser(url, self.c.root):
                ui_extra.ReaderWindow(self, url)
            return True
        return open_url(url)

    def _add_feed(self):
        try:
            self.c.add_custom_feed(self.cf_name.get(), self.cf_url.get(), dict(FEED_CATEGORIES).get(self.cf_cat.get(), "news"))
        except ValueError as e:
            self.src_note.configure(text=str(e), fg=theme.RED)
            return
        self.cf_name.set("")
        self.cf_url.set("")
        self.src_note.configure(text="Added. It will be checked on the next refresh.", fg=theme.MUTED)
        self._render_sources()
        self.start_refresh(force=True)

    def _remove_feed(self, index):
        self.c.remove_custom_feed(index)
        self._render_sources()

    def _build_settings(self, p):
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)
        self.settings_tabs = nb = ttk.Notebook(p)
        nb.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        general, feeds_tab, tor_tab, ai_tab, cam_tab = (tk.Frame(nb, bg=theme.CHARCOAL) for _ in range(5))
        nb.add(general, text="  General  ")
        nb.add(feeds_tab, text="  Feeds  ")
        nb.add(tor_tab, text="  Tor  ")
        nb.add(ai_tab, text="  AI  ")
        nb.add(cam_tab, text="  Watchtower  ")
        ui_cameras.build_tab(self, cam_tab)
        ui_extra.build_ai_tab(self, ai_tab)
        self._build_sources(feeds_tab)
        ui_extra.build_tor_tab(self, tor_tab)
        self.root.after(1500, self._tor_poll)
        p = general
        p.columnconfigure(0, weight=1)
        card = tk.Frame(p, bg=theme.PANEL)
        card.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        self.label(card, "Home", self.f_big).pack(fill="x", padx=16, pady=(14, 2))
        self.label(card, "US state codes, separated by commas. Home weather, quakes near home and the HOME marker use these.",
                   self.f_small, theme.MUTED).pack(fill="x", padx=16)
        row = tk.Frame(card, bg=theme.PANEL)
        row.pack(fill="x", padx=16, pady=8)
        self.home_var = tk.StringVar(value=", ".join(self.c.settings["home_states"]))
        tk.Entry(row, textvariable=self.home_var, width=24, bg=theme.CHARCOAL, fg=theme.BONE, insertbackground=theme.BONE,
                 relief="flat").pack(side="left", ipady=5)
        self.btn(row, "Save home", self._save_home, primary=True, small=True).pack(side="left", padx=8)
        self.home_note = self.label(row, "", self.f_small, theme.MUTED)
        self.home_note.pack(side="left")
        self.label(card, "Refresh while open (minutes)", self.f_bold).pack(fill="x", padx=16, pady=(10, 2))
        row2 = tk.Frame(card, bg=theme.PANEL)
        row2.pack(fill="x", padx=16, pady=(0, 8))
        self.auto_var = tk.IntVar(value=self.c.settings["auto_minutes"])
        tk.Spinbox(row2, from_=5, to=120, textvariable=self.auto_var, width=6, bg=theme.CHARCOAL, fg=theme.BONE,
                   relief="flat", command=self._save_auto).pack(side="left", ipady=4)
        self.label(card, "DEFCON", self.f_big).pack(fill="x", padx=16, pady=(14, 2))
        self.label(card, "The header shows two DEFCON readings. Neither is official.", self.f_small, theme.MUTED).pack(fill="x", padx=16)
        rowd = tk.Frame(card, bg=theme.PANEL)
        rowd.pack(fill="x", padx=16, pady=8)
        self.btn(rowd, "What do the DEFCON levels mean?", self.show_defcon_guide, small=True).pack(side="left")
        self.label(card, "Saved history", self.f_big).pack(fill="x", padx=16, pady=(14, 2))
        self.hist_label = self.label(card, "", self.f_small, theme.MUTED)
        self.hist_label.pack(fill="x", padx=16)
        row3 = tk.Frame(card, bg=theme.PANEL)
        row3.pack(fill="x", padx=16, pady=8)
        self.btn(row3, "Open the Overwatch folder", self._open_folder, small=True).pack(side="left")
        self.btn(row3, "Clear saved history", self._clear_history, small=True).pack(side="left", padx=8)
        self.label(card, "About the data", self.f_big).pack(fill="x", padx=16, pady=(14, 2))
        tk.Label(card, justify="left", anchor="w", wraplength=900, font=self.f_small, fg=theme.MUTED, bg=theme.PANEL,
                 text=("Overwatch reads public feeds only: official releases, government data and news outlets. It does not "
                       "log in anywhere and does not track people. Items show who reported them. Status lights measure how much "
                       "is being reported, not what is confirmed. Pins come from places named in the headline. "
                       f"Version {__version__}.")).pack(fill="x", padx=16, pady=(0, 16))

    def _save_home(self):
        try:
            self.c.set_home_states([s for s in self.home_var.get().replace(";", ",").split(",")])
        except ValueError as e:
            self.home_note.configure(text=str(e), fg=theme.RED)
            return
        self.home_note.configure(text="Saved. Refreshing home weather.", fg=theme.MUTED)
        self.refresh_view()
        self.start_refresh(force=True)

    def _save_auto(self):
        try:
            self.c.settings["auto_minutes"] = max(5, min(120, int(self.auto_var.get())))
            self.c.save_settings()
        except (ValueError, tk.TclError):
            pass

    def _open_folder(self):
        if sys.platform == "win32":
            os.startfile(self.c.root)

    def _clear_history(self):
        if messagebox.askyesno("Clear saved history", "Remove every saved item and source record from this PC?\nSettings stay.",
                               parent=self.root):
            self.c.clear_history()
            self.refresh_view()

    # ----- refreshing -----
    def start_refresh(self, force=False):
        if self.worker and self.worker.is_alive():
            return False
        self.cancel.clear()
        self.status_top.configure(text="Refreshing...")

        def run():
            try:
                res = self.c.refresh(progress=lambda m: self.q.put(("p", m)), cancel=self.cancel, force=force)
                self.q.put(("done", res))
            except Exception as e:
                self.q.put(("err", f"{type(e).__name__}: {e}"))
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        return True

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "p":
                    self.status_top.configure(text=val)
                    if self.splash_win:
                        self.splash_status.configure(text=val)
                elif kind == "tr":
                    if val:
                        self.refresh_view()
                    self._status()
                elif kind in ("done", "err"):
                    self.last_result = val if kind == "done" else None
                    self.refresh_view()
                    if kind == "done":
                        self._auto_translate()
                        self._auto_pin()
                    if kind == "err":
                        self.status_top.configure(text="Refresh problem: " + val)
                    self._close_splash_soon()
        except queue.Empty:
            pass
        if self.splash_win and time.time() - self.splash_started > 12:
            self._close_splash()
        self.root.after(100, self._poll)

    def _tick(self):
        self._status()
        last = self.c.last_refresh()
        if self.auto and last and self.c.now() - last > self.c.settings["auto_minutes"] * 60:
            self.start_refresh()
        self.root.after(30_000, self._tick)

    def _status(self):
        now = self.c.now()
        last = self.c.last_refresh()
        ok, total = self.c.healthy_counts()
        if not last:
            self.status_top.configure(text="No data yet. Press Refresh now.")
        else:
            offline = total and ok == 0
            self.status_top.configure(text=("Offline: showing saved data from " if offline else "Updated ") + ago(last, now),
                                      fg=theme.AMBER if offline else theme.MUTED)
        self.statusbar.configure(text=f"   Saved on this PC: {self.c.store.count():,} items  ·  "
                                      f"Sources working: {ok} of {total}  ·  "
                                      "If the internet drops, Overwatch shows the last saved picture with its age")
        self.hist_label.configure(text=f"{self.c.store.count():,} items kept for 30 days in {self.c.root}")

    # ----- splash -----
    def _show_splash(self):
        self.root.withdraw()
        s = tk.Toplevel(self.root)
        s.overrideredirect(True)
        bg = "#0A0D10"
        s.configure(bg=bg)
        w, h = 520, 580
        s.geometry(f"{w}x{h}+{(s.winfo_screenwidth() - w) // 2}+{max(0, (s.winfo_screenheight() - h) // 3)}")
        try:
            self.splash_img = tk.PhotoImage(file=os.path.join(DATA, "splash.png"))
            tk.Label(s, image=self.splash_img, bg=bg, bd=0).pack()
        except tk.TclError:
            tk.Label(s, text="CINDRIX OVERWATCH", font=self.f_big, fg=theme.BONE, bg=bg).pack(pady=200)
        self.splash_status = tk.Label(s, text="Starting...", font=self.f_small, fg=theme.MUTED, bg=bg)
        self.splash_status.pack(pady=(4, 0))
        tk.Label(s, text=f"Version {__version__}", font=self.f_small, fg=theme.MUTED, bg=bg).pack(pady=2)
        s.attributes("-topmost", True)
        s.update()
        self.splash_win = s

    def _close_splash_soon(self):
        if self.splash_win:
            wait = max(0, 1.8 - (time.time() - self.splash_started))
            self.root.after(int(wait * 1000), self._close_splash)

    def _close_splash(self):
        if self.splash_win:
            self.splash_win.destroy()
            self.splash_win = None
            self.root.deiconify()
            self.root.lift()

    def _quit(self):
        try:
            self.watchtower.shutdown()
            if getattr(self, "link_server", None):
                self.link_server.stop()
        finally:
            self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.mainloop()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().run()
