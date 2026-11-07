"""Settings > Watchtower: the camera list (any number, each with an on/off switch), adding a camera, and the small
"Which cameras work?" window that lists every supported make."""

import tkinter as tk
from tkinter import ttk

from . import cameras, theme

TIER_COLORS = {"works": theme.GREEN, "enable": theme.BLUE, "some": theme.AMBER, "no": theme.RED}
TIER_FILTERS = [("All", None), ("Works", "works"), ("Turn it on first", "enable"), ("Some models", "some"), ("Not supported", "no")]


def build_tab(app, p):
    p.columnconfigure(0, weight=1)
    p.rowconfigure(2, weight=1)
    head = tk.Frame(p, bg=theme.CHARCOAL)
    head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
    app.label(head, "Watchtower: your cameras", app.f_big).pack(side="left")
    link = tk.Label(head, text="Which cameras work?", font=app.f_small, fg=theme.MUTED, bg=theme.CHARCOAL, cursor="hand2")
    link.pack(side="right")
    link.bind("<Button-1>", lambda e: SupportedWindow(app))
    link.bind("<Enter>", lambda e: link.configure(fg=theme.BLUE))
    link.bind("<Leave>", lambda e: link.configure(fg=theme.MUTED))
    add = tk.Frame(p, bg=theme.PANEL)
    add.grid(row=1, column=0, sticky="ew", padx=14, pady=8)
    app.label(add, "Add a camera. Any number. Each one gets its own on/off switch below.", app.f_bold).grid(
        row=0, column=0, columnspan=8, sticky="w", padx=12, pady=(10, 4))
    app.wt_name, app.wt_brand, app.wt_host = tk.StringVar(), tk.StringVar(), tk.StringVar()
    app.wt_port, app.wt_user, app.wt_pass = tk.StringVar(), tk.StringVar(), tk.StringVar()
    choices = [b for b in cameras.brands() if b["tier"] != "no"]
    names = [b["name"] for b in choices]
    app.wt_brand.set(next(b["name"] for b in choices if b["id"] == "other"))

    def field(r, c, label, var, width, show=None):
        app.label(add, label, app.f_small, theme.MUTED).grid(row=r, column=c, sticky="w", padx=(12, 4), pady=(2, 0))
        e = tk.Entry(add, textvariable=var, width=width, bg=theme.CHARCOAL, fg=theme.BONE, insertbackground=theme.BONE, relief="flat",
                     show=show or "")
        e.grid(row=r + 1, column=c, sticky="w", padx=(12, 4), pady=(0, 6), ipady=4)
    field(1, 0, "Name", app.wt_name, 18)
    app.label(add, "Make", app.f_small, theme.MUTED).grid(row=1, column=1, sticky="w", padx=(12, 4), pady=(2, 0))
    cb = ttk.Combobox(add, textvariable=app.wt_brand, values=names, width=30, state="readonly")
    cb.grid(row=2, column=1, sticky="w", padx=(12, 4), pady=(0, 6))
    field(1, 2, "Address (IP, or the whole rtsp:// address)", app.wt_host, 34)
    field(1, 3, "Port (if not usual)", app.wt_port, 8)
    field(1, 4, "Username", app.wt_user, 14)
    field(1, 5, "Password", app.wt_pass, 14, show="•")
    app.btn(add, "Add camera", lambda: _add(app, choices), small=True, primary=True).grid(row=2, column=6, padx=10, pady=(0, 6))
    app.wt_hint = tk.Label(add, text="", font=app.f_small, fg=theme.MUTED, bg=theme.PANEL, justify="left", anchor="w", wraplength=1000)
    app.wt_hint.grid(row=3, column=0, columnspan=8, sticky="w", padx=12, pady=(0, 2))
    app.wt_note = app.label(add, "", app.f_small, theme.MUTED)
    app.wt_note.grid(row=4, column=0, columnspan=8, sticky="w", padx=12, pady=(0, 10))

    def picked(*_):
        b = next((x for x in choices if x["name"] == app.wt_brand.get()), None)
        if b:
            app.wt_hint.configure(text=(b.get("setup") or b.get("note") or ""))
    cb.bind("<<ComboboxSelected>>", picked)
    picked()
    # the list
    box = tk.Frame(p, bg=theme.CHARCOAL)
    box.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 10))
    box.rowconfigure(0, weight=1)
    box.columnconfigure(0, weight=1)
    cv = tk.Canvas(box, bg=theme.CHARCOAL, highlightthickness=0)
    sb = ttk.Scrollbar(box, orient="vertical", command=cv.yview)
    cv.configure(yscrollcommand=sb.set)
    cv.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")
    app.wt_list = tk.Frame(cv, bg=theme.CHARCOAL)
    win = cv.create_window(0, 0, window=app.wt_list, anchor="nw")
    app.wt_list.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
    cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
    app.wt_rows = {}


def _add(app, choices):
    b = next((x for x in choices if x["name"] == app.wt_brand.get()), None)
    try:
        app.c.add_camera(app.wt_name.get(), b["id"] if b else "other", app.wt_host.get(), app.wt_user.get(), app.wt_pass.get(),
                         app.wt_port.get().strip() or None)
    except ValueError as e:
        app.wt_note.configure(text=str(e), fg=theme.RED)
        return
    for v in (app.wt_name, app.wt_host, app.wt_port, app.wt_user, app.wt_pass):
        v.set("")
    app.wt_note.configure(text="Added. It is in the list below with its own switch.", fg=theme.MUTED)
    render(app)


def render(app):
    wt = getattr(app, "watchtower", None)
    if wt:
        wt.refresh()
    for w in app.wt_list.winfo_children():
        w.destroy()
    app.wt_rows = {}
    cams = app.c.cameras()
    if not cams:
        app.label(app.wt_list, "No cameras yet. Add one above. Not sure what works? Open \"Which cameras work?\" at the top.",
                  app.f_small, theme.MUTED).pack(fill="x", padx=8, pady=10)
    for cam in cams:
        on = cam.get("enabled", True)
        fr = tk.Frame(app.wt_list, bg=theme.PANEL)
        fr.pack(fill="x", pady=2)
        sw = tk.Label(fr, text="ON " if on else " OFF", font=app.f_bold, width=5, cursor="hand2",
                      bg=theme.BLUE if on else theme.PANEL_HIGH, fg=theme.ON_BLUE if on else theme.MUTED)
        sw.pack(side="left", padx=10, pady=8)
        sw.bind("<Button-1>", lambda e, i=cam["id"], now=on: _flip(app, i, not now))
        info = tk.Frame(fr, bg=theme.PANEL)
        info.pack(side="left", fill="x", expand=True, pady=4)
        tk.Label(info, text=cam["name"], font=app.f_bold, fg=theme.BONE if on else theme.MUTED, bg=theme.PANEL, anchor="w").pack(fill="x")
        b = cameras.brand(cam["brand"]) or {}
        tk.Label(info, text=f"{b.get('name', 'Camera')}  ·  {cameras.shown_address(cam)}" + ("  ·  login saved" if cam.get("user") else ""),
                 font=app.f_small, fg=theme.MUTED, bg=theme.PANEL, anchor="w").pack(fill="x")
        rm = tk.Label(fr, text="Remove", font=app.f_small, fg=theme.BLUE, bg=theme.PANEL, cursor="hand2")
        rm.pack(side="right", padx=12)
        rm.bind("<Button-1>", lambda e, i=cam["id"]: _remove(app, i))
        app.wt_rows[cam["id"]] = sw


def _flip(app, cam_id, enable):
    app.c.set_camera_enabled(cam_id, enable)
    render(app)


def _remove(app, cam_id):
    app.c.remove_camera(cam_id)
    render(app)


class SupportedWindow:
    """A pop-up listing every make Watchtower can show, with the address style each one uses."""

    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root)
        w.title("Which cameras work?")
        w.configure(bg=theme.CHARCOAL)
        w.geometry("860x640")
        w.transient(app.root)
        w.columnconfigure(0, weight=1)
        w.rowconfigure(2, weight=1)
        tk.Label(w, text="Cameras Watchtower can show", font=app.f_big, fg=theme.BONE, bg=theme.CHARCOAL, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(14, 2))
        cat = cameras.catalog()
        tk.Label(w, text=cat["about"], font=app.f_small, fg=theme.MUTED, bg=theme.CHARCOAL, justify="left", anchor="w", wraplength=800).grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
        self.tier = None
        bar = tk.Frame(w, bg=theme.CHARCOAL)
        bar.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 0))
        self.chips = []
        for text, key in TIER_FILTERS:
            b = tk.Button(bar, text=text, relief="flat", bd=0, padx=10, pady=4, font=app.f_small, cursor="hand2",
                          command=lambda k=key: self._set_tier(k))
            b.pack(side="left", padx=(0, 6))
            self.chips.append((key, b))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self._render())
        tk.Entry(bar, textvariable=self.search, width=22, bg=theme.PANEL, fg=theme.BONE, insertbackground=theme.BONE, relief="flat").pack(
            side="right", ipady=4)
        tk.Label(bar, text="Search", font=app.f_small, fg=theme.MUTED, bg=theme.CHARCOAL).pack(side="right", padx=6)
        mid = tk.Frame(w, bg=theme.CHARCOAL)
        mid.grid(row=2, column=0, sticky="nsew", padx=16, pady=6)
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        self.cv = tk.Canvas(mid, bg=theme.CHARCOAL, highlightthickness=0)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.inner = tk.Frame(self.cv, bg=theme.CHARCOAL)
        self._win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self._win, width=e.width))
        self.cv.bind("<Enter>", lambda e: self.cv.bind_all("<MouseWheel>", lambda ev: self.cv.yview_scroll(-1 if ev.delta > 0 else 1, "units")))
        self.cv.bind("<Leave>", lambda e: self.cv.unbind_all("<MouseWheel>"))
        app.btn(w, "Close", self.close, small=True).grid(row=4, column=0, sticky="e", padx=16, pady=10)
        self._render()
        try:
            w.grab_set()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.cv.unbind_all("<MouseWheel>")
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()

    def _set_tier(self, key):
        self.tier = key
        self._render()

    def _render(self):
        a = self.app
        for key, b in self.chips:
            on = key == self.tier
            b.configure(bg=theme.BLUE if on else theme.PANEL_HIGH, fg=theme.ON_BLUE if on else theme.BONE)
        for w in self.inner.winfo_children():
            w.destroy()
        tiers = cameras.catalog()["tiers"]
        q = self.search.get().strip().lower()
        shown = 0
        for b in cameras.brands():
            if self.tier and b["tier"] != self.tier:
                continue
            if q and q not in (b["name"] + " " + b.get("models", "")).lower():
                continue
            shown += 1
            fr = tk.Frame(self.inner, bg=theme.PANEL)
            fr.pack(fill="x", pady=3)
            top = tk.Frame(fr, bg=theme.PANEL)
            top.pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(top, text=b["name"], font=a.f_head, fg=theme.BONE, bg=theme.PANEL).pack(side="left")
            tk.Label(top, text=tiers[b["tier"]], font=a.f_small, fg=TIER_COLORS[b["tier"]], bg=theme.PANEL).pack(side="left", padx=10)
            tk.Label(fr, text=b["models"], font=a.f_small, fg=theme.BONE, bg=theme.PANEL, justify="left", anchor="w", wraplength=760).pack(
                fill="x", padx=12)
            if b["main"]:
                ex = cameras.build_address(b["id"], "CAMERA-IP", None, "main")
                sub = cameras.build_address(b["id"], "CAMERA-IP", None, "sub") if b["sub"] else ""
                tk.Label(fr, text="Address style:  " + ex + (f"\n Sub-stream:  {sub}" if sub else ""), font=a.f_small, fg=theme.MUTED,
                         bg=theme.PANEL, justify="left", anchor="w", wraplength=760).pack(fill="x", padx=12, pady=(2, 0))
            if b.get("setup"):
                tk.Label(fr, text="Setup:  " + b["setup"], font=a.f_small, fg=theme.MUTED, bg=theme.PANEL, justify="left", anchor="w",
                         wraplength=760).pack(fill="x", padx=12, pady=(2, 0))
            tk.Label(fr, text=b["note"], font=a.f_small, fg=theme.MUTED, bg=theme.PANEL, justify="left", anchor="w",
                     wraplength=760).pack(fill="x", padx=12, pady=(2, 8))
        if not shown:
            tk.Label(self.inner, text="Nothing matches. Try another word or filter.", font=a.f_small, fg=theme.MUTED, bg=theme.CHARCOAL).pack(pady=20)
