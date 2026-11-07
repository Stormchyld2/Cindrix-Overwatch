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
        self.search.trace_add("write", lambda *a: self.render())
        self.items, self.item = [], None
        self._build(parent)

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
        a.btn(left, "Open the Brief", lambda: a.show_page("brief"), small=True).pack(fill="x", padx=12, pady=(16, 4))
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

    # ----- the list -----
    def set_channel(self, key):
        self.channel = key
        self.render()

    def toggle_deploy(self):
        self.deploy_only = not self.deploy_only
        self.render()

    def show(self):
        self.render()

    def render(self):
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
        self.render()
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
            self.render()
