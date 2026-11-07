"""The Intel page: the same feeds the Discord feed bot posted, in its four channels, readable here, with pins you place yourself."""

import tkinter as tk
from tkinter import ttk

from . import reader, sources, theme
from .model import KIND_LABELS, TRUST_LABELS
from .ui_extra import Worker

LIST_LIMIT = 150


class IntelPage:
    def __init__(self, app, parent):
        self.app, self.c = app, app.c
        self.channel = "military"
        self.deploy_only = False
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.render_reading())
        self.items, self.item = [], None
        self.mode = "dash"
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.dash_frame = tk.Frame(parent, bg=theme.CHARCOAL)
        self.reading = tk.Frame(parent, bg=theme.CHARCOAL)
        for f in (self.dash_frame, self.reading):
            f.grid(row=0, column=0, sticky="nsew")
        self._build(self.reading)
        self._build_dash(self.dash_frame)
        self.dash_frame.tkraise()

    # ----- layout -----
    def _build(self, p):
        a = self.app
        p.columnconfigure(1, weight=1)
        p.columnconfigure(2, weight=1)
        p.rowconfigure(0, weight=1)
        left = tk.Frame(p, bg=theme.PANEL, width=230)
        left.grid(row=0, column=0, sticky="ns", padx=(10, 4), pady=10)
        left.grid_propagate(False)
        a.label(left, "INTEL CHANNELS", a.f_small, theme.MUTED).pack(fill="x", padx=14, pady=(12, 6))
        self.chan_btns = {}
        for key, name, _ in sources.INTEL_CHANNELS:
            b = tk.Button(left, text=name, command=lambda k=key: self.set_channel(k), relief="flat", bd=0, anchor="w",
                          padx=14, pady=8, font=a.f_bold, cursor="hand2")
            b.pack(fill="x", padx=8, pady=2)
            self.chan_btns[key] = b
        self.deploy_btn = tk.Button(left, text="Troop movements only", command=self.toggle_deploy, relief="flat", bd=0, anchor="w",
                                    padx=14, pady=6, font=a.f_small, cursor="hand2")
        self.deploy_btn.pack(fill="x", padx=8, pady=(10, 2))
        e = tk.Entry(left, textvariable=self.search, bg=theme.CHARCOAL, fg=theme.BONE, insertbackground=theme.BONE, relief="flat",
                     font=a.f_body, highlightthickness=1, highlightbackground=theme.OUTLINE, highlightcolor=theme.BLUE)
        e.pack(fill="x", padx=12, pady=(10, 4), ipady=5)
        a.label(left, "Search these articles", a.f_small, theme.MUTED).pack(fill="x", padx=14)
        a.btn(left, "\u2190 Dashboard", self.go_dash, small=True, primary=True).pack(fill="x", padx=12, pady=(16, 4))
        a.btn(left, "Open the Brief", lambda: a.show_page("brief"), small=True).pack(fill="x", padx=12, pady=(4, 4))
        self.note = a.label(left, "", a.f_small, theme.MUTED, justify="left", wraplength=200)
        self.note.pack(fill="x", padx=14, pady=8)
        # article list
        mid = tk.Frame(p, bg=theme.PANEL)
        mid.grid(row=0, column=1, sticky="nsew", padx=4, pady=10)
        self.canvas = tk.Canvas(mid, bg=theme.PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        self.inner = tk.Frame(self.canvas, bg=theme.PANEL)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", lambda ev: self.canvas.yview_scroll(-1 if ev.delta > 0 else 1, "units")))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        # reader
        right = tk.Frame(p, bg=theme.PANEL)
        right.grid(row=0, column=2, sticky="nsew", padx=(4, 10), pady=10)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)
        self.r_kind = a.label(right, "Pick an article on the left", a.f_small, theme.MUTED)
        self.r_kind.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
        self.r_title = tk.Label(right, text="", font=a.f_head, fg=theme.BONE, bg=theme.PANEL, anchor="w", justify="left", wraplength=520)
        self.r_title.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 0))
        self.r_meta = a.label(right, "", a.f_small, theme.MUTED)
        self.r_meta.grid(row=2, column=0, sticky="ew", padx=14)
        self.text = tk.Text(right, wrap="word", bg=theme.CHARCOAL, fg=theme.BONE, relief="flat", font=a.f_body, state="disabled",
                            padx=12, pady=10)
        self.text.grid(row=3, column=0, sticky="nsew", padx=14, pady=8)
        bar = tk.Frame(right, bg=theme.PANEL)
        bar.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.read_btn = a.btn(bar, "Read the article here", self.read_full, primary=True, small=True)
        self.read_btn.pack(side="left")
        a.btn(bar, "Open in browser", self.open_browser, small=True).pack(side="left", padx=6)
        a.btn(bar, "Show on map", self.show_on_map, small=True).pack(side="left")
        pin = tk.Frame(right, bg=theme.PANEL)
        pin.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 12))
        a.label(pin, "Pin it:", a.f_small, theme.MUTED, bg=theme.PANEL).pack(side="left")
        a.btn(pin, "Click the map", self.pin_by_click, small=True).pack(side="left", padx=6)
        self.place = tk.StringVar()
        pe = tk.Entry(pin, textvariable=self.place, bg=theme.CHARCOAL, fg=theme.BONE, insertbackground=theme.BONE, relief="flat",
                      font=a.f_body, width=18, highlightthickness=1, highlightbackground=theme.OUTLINE, highlightcolor=theme.BLUE)
        pe.pack(side="left", ipady=4)
        pe.bind("<Return>", lambda e: self.pin_by_name())
        a.btn(pin, "Pin to place", self.pin_by_name, small=True).pack(side="left", padx=6)
        a.btn(pin, "Remove my pin", self.unpin, small=True).pack(side="left")
        self.pin_note = a.label(right, "", a.f_small, theme.MUTED, justify="left", wraplength=520)
        self.pin_note.grid(row=6, column=0, sticky="ew", padx=14, pady=(0, 10))


    # ----- the dashboard -----
    def _build_dash(self, d):
        a = self.app
        d.columnconfigure(0, weight=1)
        d.rowconfigure(0, weight=1)
        canvas = tk.Canvas(d, bg=theme.CHARCOAL, highlightthickness=0)
        sb = ttk.Scrollbar(d, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        body = tk.Frame(canvas, bg=theme.CHARCOAL)
        win = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(-1 if ev.delta > 0 else 1, "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        self.dash_canvas = canvas
        body.columnconfigure(0, weight=2, uniform="dash")
        body.columnconfigure(1, weight=1, uniform="dash")
        body.columnconfigure(2, weight=1, uniform="dash")
        # status lights
        strip = tk.Frame(body, bg=theme.CHARCOAL)
        strip.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 6))
        self.d_tiles = []
        for i in range(9):
            strip.columnconfigure(i, weight=1, uniform="dtile")
            t = tk.Frame(strip, bg=theme.PANEL)
            t.grid(row=0, column=i, sticky="nsew", padx=4)
            bar = tk.Frame(t, bg=theme.GREEN, height=3)
            bar.pack(fill="x")
            name = a.label(t, "", a.f_small, theme.MUTED)
            name.pack(fill="x", padx=8, pady=(5, 0))
            word = a.label(t, "", a.f_head)
            word.pack(fill="x", padx=8)
            note = a.label(t, "", a.f_small, theme.MUTED)
            note.pack(fill="x", padx=8, pady=(0, 5))
            self.d_tiles.append((bar, name, word, note))
        # Top 10 (left, tall) and the channel panels
        self.d_top = self._panel(body, "TOP 10 FOR EARLY WARNING", theme.BLUE, 1, 0, rowspan=3, link=("Open the Brief", lambda: a.show_page("brief")))
        self.d_panels = {}
        specs = (("troops", "TROOP MOVEMENTS", theme.AMBER, 1, 1, 2, None),
                 ("military", "MILITARY", theme.BLUE, 2, 1, 1, "military"),
                 ("world", "WORLD NEWS", theme.MUTED, 2, 2, 1, "world"),
                 ("cyber", "CYBER", theme.KIND_COLORS["cyber"], 3, 1, 1, "cyber"),
                 ("alerts", "ALERTS AND WEATHER", theme.AMBER, 3, 2, 1, "alerts"))
        for key, title, col, r, c, span, chan in specs:
            if key == "troops":
                link = ("See all \u2192", lambda: self.go_reading("military", deploy=True))
            else:
                link = ("See all \u2192", lambda ch=chan: self.go_reading(ch))
            self.d_panels[key] = self._panel(body, title, col, r, c, colspan=span, link=link)
        for r in (1, 2, 3):
            body.rowconfigure(r, weight=1)
        self.d_foot = a.label(body, "Click a headline to read it. Pin stories that are not on the map, with a click on the map or a typed place.",
                              a.f_small, theme.MUTED)
        self.d_foot.grid(row=4, column=0, columnspan=3, sticky="w", padx=14, pady=(2, 12))

    def _panel(self, parent, title, color, row, col, rowspan=1, colspan=1, link=None):
        a = self.app
        outer = tk.Frame(parent, bg=theme.PANEL)
        outer.grid(row=row, column=col, rowspan=rowspan, columnspan=colspan, sticky="nsew", padx=6, pady=6)
        head = tk.Frame(outer, bg=theme.PANEL)
        head.pack(fill="x", padx=14, pady=(12, 4))
        tk.Frame(head, bg=color, width=10, height=10).pack(side="left", padx=(0, 8))
        tk.Label(head, text=title, font=a.f_head, fg=theme.BONE, bg=theme.PANEL).pack(side="left")
        count = tk.Label(head, text="", font=a.f_small, fg=theme.MUTED, bg=theme.PANEL)
        count.pack(side="left", padx=8)
        if link:
            b = tk.Label(head, text=link[0], font=a.f_small, fg=theme.BLUE, bg=theme.PANEL, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda e, f=link[1]: f())
        body = tk.Frame(outer, bg=theme.PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        body.labels = []
        body.count = count
        body.bind("<Configure>", lambda e, b=body: [l.configure(wraplength=max(120, e.width - 110)) for l in b.labels])
        return body

    def _dash_rows(self, body, entries, numbered=False):
        """entries: list of (item, reasons). Each row opens the reader; unpinned ones get a Pin button."""
        a = self.app
        from .scoring import is_deployment
        from .ui import ago
        for w in body.winfo_children():
            w.destroy()
        body.labels = []
        if not entries:
            a.label(body, "Nothing here yet. Press Refresh now while online.", a.f_small, theme.MUTED, bg=theme.PANEL).pack(fill="x", padx=6, pady=8)
            return
        now = self.c.now()
        for k, (it, reasons) in enumerate(entries, 1):
            col = theme.KIND_COLORS.get(it.kind, theme.MUTED)
            row = tk.Frame(body, bg=theme.PANEL_HIGH if numbered else theme.PANEL, cursor="hand2")
            row.pack(fill="x", pady=2)
            if numbered:
                tk.Label(row, text=str(k), font=a.f_big, fg=col, bg=theme.PANEL_HIGH, width=2).pack(side="left", padx=(6, 2))
            box = tk.Frame(row, bg=row["bg"])
            box.pack(side="left", fill="x", expand=True, padx=6, pady=5)
            t = tk.Label(box, text=it.shown, font=a.f_bold, fg=theme.BONE, bg=row["bg"], anchor="w", justify="left", wraplength=360)
            t.pack(fill="x")
            body.labels.append(t)
            meta = tk.Frame(box, bg=row["bg"])
            meta.pack(fill="x")
            tk.Label(meta, text=f"{it.source}  \u00b7  {ago(it.ts, now)}", font=a.f_small, fg=theme.MUTED, bg=row["bg"]).pack(side="left")
            tags = list(reasons) if numbered else []
            if not numbered and is_deployment(it):
                tags.append("troop movement")
            if not it.pinned:
                tags.append("not on map")
            for text in tags:
                tk.Label(meta, text=text.upper(), font=a.f_small, fg=theme.AMBER if text in ("force movement", "troop movement") else theme.BLUE,
                         bg=theme.CHARCOAL, padx=5).pack(side="left", padx=(6, 0))
            if not it.pinned and it.kind != "cyber":
                pb = tk.Label(row, text="Pin", font=a.f_small, fg=theme.ON_BLUE, bg=theme.BLUE, padx=8, pady=2, cursor="hand2")
                pb.pack(side="right", padx=6)
                pb._no_open = True
                pb.bind("<Button-1>", lambda e, i=it: self.app.begin_pin(i, self._pinned_dash))

            def bind(w, i=it):
                if getattr(w, "_no_open", False):
                    return
                w.bind("<Button-1>", lambda e, i=i: self.go_reading(self._channel_of(i), i))
                for ch in w.winfo_children():
                    bind(ch, i)
            bind(row)

    def _channel_of(self, it):
        return sources.intel_channel(it)

    def _pinned_dash(self, name=""):
        self.app.refresh_view()
        self.render_dash()

    def render_dash(self):
        from .scoring import is_deployment, is_home
        c = self.c
        for (bar, name, word, note), (iid, label, lvl, w, n) in zip(self.d_tiles, c.indicators()):
            col = theme.LEVEL_COLORS[lvl]
            bar.configure(bg=col)
            name.configure(text=label.upper())
            word.configure(text=w, fg=col)
            note.configure(text=n)
        self._dash_rows(self.d_top, c.top_warnings(10), numbered=True)
        self.d_top.count.configure(text="")
        home = c.settings.get("home_states") or []
        day = c.feed(limit=1000, hours=24)
        troops = [i for i in day if is_deployment(i)][:5]
        self._dash_rows(self.d_panels["troops"], [(i, []) for i in troops])
        self.d_panels["troops"].count.configure(text=f"{len(troops)} in 24 h")
        for key in ("military", "world", "cyber", "alerts"):
            items = c.feed(channel=key, limit=1000, hours=48)
            if key == "alerts":     # home alerts first, then the most serious
                items.sort(key=lambda i: (not is_home(i, home), -i.severity, -i.ts))
            self._dash_rows(self.d_panels[key], [(i, []) for i in items[:5]])
            self.d_panels[key].count.configure(text=str(len(items)))
        self.dash_canvas.yview_moveto(0)

    # ----- the list -----
    def set_channel(self, key):
        self.channel = key
        self.render_reading()

    def toggle_deploy(self):
        self.deploy_only = not self.deploy_only
        self.render_reading()

    def show(self):
        self.render()

    def render(self):
        if self.mode == "dash":
            self.render_dash()
        else:
            self.render_reading()

    def go_dash(self):
        self.mode = "dash"
        self.dash_frame.tkraise()
        self.render_dash()

    def go_reading(self, channel=None, item=None, deploy=False):
        self.mode = "reading"
        if channel:
            self.channel = channel
        self.deploy_only = deploy
        self.reading.tkraise()
        self.render_reading()
        if item is not None:
            self.open_item(item)

    def render_reading(self):
        a = self.app
        for key, b in self.chan_btns.items():
            n = len(self.c.feed(channel=key, limit=1000, hours=48))
            name = next(nm for k, nm, _ in sources.INTEL_CHANNELS if k == key)
            on = key == self.channel
            b.configure(text=f"{name}   ({n})", bg=theme.BLUE if on else theme.PANEL, fg=theme.ON_BLUE if on else theme.BONE)
        self.deploy_btn.configure(bg=theme.BLUE if self.deploy_only else theme.PANEL_HIGH,
                                  fg=theme.ON_BLUE if self.deploy_only else theme.MUTED)
        for w in self.inner.winfo_children():
            w.destroy()
        self.items = self.c.feed(channel=self.channel, text=self.search.get(), deploy_only=self.deploy_only, limit=LIST_LIMIT, hours=72)
        if not self.items:
            a.label(self.inner, "Nothing here yet. Press Refresh now while online.\nSaved items show even offline.", a.f_small,
                    theme.MUTED, justify="left").pack(fill="x", padx=8, pady=12)
        for it in self.items:
            self._card(it)
        self.canvas.yview_moveto(0)
        if self.channel == "alerts" and not self.c.settings.get("home_states"):
            self.note.configure(text="Set your home states in Settings to get your local weather alerts here.")
        else:
            self.note.configure(text="")
        if self.item is not None:      # keep the open article in step after a refresh (a pin may have changed)
            fresh = next((i for i in self.items if i.uid == self.item.uid), None)
            if fresh is not None:
                self.item = fresh

    def _card(self, it):
        a = self.app
        col = theme.KIND_COLORS.get(it.kind, theme.MUTED)
        outer = tk.Frame(self.inner, bg=theme.PANEL_HIGH, cursor="hand2")
        outer.pack(fill="x", pady=3, padx=(0, 8))
        tk.Frame(outer, bg=col, width=4).pack(side="left", fill="y")
        box = tk.Frame(outer, bg=theme.PANEL_HIGH)
        box.pack(side="left", fill="both", expand=True, padx=8, pady=6)
        meta = tk.Frame(box, bg=theme.PANEL_HIGH)
        meta.pack(fill="x")
        from .scoring import is_deployment
        tags = [(KIND_LABELS[it.kind], col)]
        if is_deployment(it):
            tags.append(("TROOP MOVEMENT", theme.BLUE))
        if it.mine:
            tags.append(("MY PIN", theme.BONE))
        for text, c in tags:
            tk.Label(meta, text=text, font=a.f_small, fg=c, bg=theme.PANEL_HIGH).pack(side="left", padx=(0, 6))
        from .ui import ago
        tk.Label(meta, text=f"{it.source}  \u00b7  {ago(it.ts, self.c.now())}", font=a.f_small, fg=theme.MUTED,
                 bg=theme.PANEL_HIGH).pack(side="left")
        tk.Label(box, text=it.shown, font=a.f_bold, fg=theme.BONE, bg=theme.PANEL_HIGH, anchor="w", justify="left", wraplength=380).pack(fill="x")
        if it.summary:
            tk.Label(box, text=it.summary[:180] + ("..." if len(it.summary) > 180 else ""), font=a.f_small, fg=theme.MUTED,
                     bg=theme.PANEL_HIGH, anchor="w", justify="left", wraplength=380).pack(fill="x")

        def bind(w):
            w.bind("<Button-1>", lambda e, i=it: self.open_item(i))
            for ch in w.winfo_children():
                bind(ch)
        bind(outer)

    # ----- the reader -----
    def _set_text(self, text):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.configure(state="disabled")

    def open_item(self, it):
        self.item = it
        self.pin_note.configure(text="")
        self.r_kind.configure(text=KIND_LABELS[it.kind] + (f"  \u00b7  {TRUST_LABELS[it.trust]}"), fg=theme.KIND_COLORS.get(it.kind, theme.MUTED))
        self.r_title.configure(text=it.shown)
        from .ui import ago
        place = f"  \u00b7  {it.place}" if it.place else "  \u00b7  not on the map yet"
        self.r_meta.configure(text=f"{it.source}  \u00b7  {ago(it.ts, self.c.now())}{place}")
        self._set_text(it.summary or "(This feed sent a headline only. Use \"Read the article here\" to load the page as plain text.)")
        self.read_btn.configure(state="normal" if it.url else "disabled")

    def read_full(self):
        it = self.item
        if not it or not it.url:
            return
        self.read_btn.configure(state="disabled")
        self._set_text("Loading the article...")

        def done(kind, val):
            self.read_btn.configure(state="normal")
            if self.item is not it:
                return
            if kind == "err":
                self._set_text(f"Could not load it ({val}). Use Open in browser.")
                return
            status, html = val
            if status != 200:
                self._set_text(f"Could not load it ({'HTTP ' + str(status) if status else html}). Use Open in browser.")
                return
            title, txt, _ = reader.html_to_text(html, it.url)
            self._set_text((txt or "(No readable text on this page. Use Open in browser.)")[:60000])
        Worker(self.app.root, lambda: self.c.read_page(it.url, False), done)

    def open_browser(self):
        if self.item and self.item.url:
            self.app.open_link(self.item.url)

    def show_on_map(self):
        if self.item and self.item.pinned:
            self.app.show_page("war")
            self.app.select(self.item, from_feed=True)
        else:
            self.pin_note.configure(text="This one is not on the map yet. Pin it with the buttons below.", fg=theme.AMBER)

    # ----- your own pins -----
    def pin_by_click(self):
        if not self.item:
            self.pin_note.configure(text="Pick an article first.", fg=theme.AMBER)
            return
        self.app.begin_pin(self.item, self._pinned)

    def pin_by_name(self):
        if not self.item:
            self.pin_note.configure(text="Pick an article first.", fg=theme.AMBER)
            return
        name = self.c.pin_item_by_name(self.item.uid, self.place.get())
        if not name:
            self.pin_note.configure(text="That place is not in the built-in list. Try a city or country, or use Click the map.", fg=theme.AMBER)
            return
        self._pinned(name)

    def _pinned(self, name=""):
        self.pin_note.configure(text=f"Pinned{(' at ' + name) if name else ''}. It stays until you remove it.", fg=theme.MUTED)
        self.app.refresh_view()
        self.render_reading()
        if self.item:
            fresh = next((i for i in self.c.all_items(72) if i.uid == self.item.uid), None)
            if fresh:
                self.item = fresh
                self.open_item(fresh)

    def unpin(self):
        if self.item:
            self.c.unpin_item(self.item.uid)
            self.pin_note.configure(text="Your pin was removed.", fg=theme.MUTED)
            self.app.refresh_view()
            self.render_reading()
