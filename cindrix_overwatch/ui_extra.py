"""Window parts for feeds and Tor: the feed assistant, the Tor tab and the no-script page reader."""

import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import discover, reader, sources, theme, tor


def _entry(parent, var, width):
    return tk.Entry(parent, textvariable=var, width=width, bg=theme.CHARCOAL, fg=theme.BONE,
                    insertbackground=theme.BONE, relief="flat")


def outlet_home(text):
    """If the text names a known outlet, return its website, else None."""
    t = text.strip().lower()
    if not t or "." in t:
        return None
    for name, home, _ in sources.ONION_OUTLETS:
        if t in name.lower():
            return home
    return None


class Worker:
    """Runs a function off the window thread and hands the result back through the window's own loop."""

    def __init__(self, win, fn, done):
        self.q = queue.Queue()
        self.win, self.done = win, done

        def run():
            try:
                self.q.put(("ok", fn()))
            except Exception as e:
                self.q.put(("err", str(e) or type(e).__name__))
        threading.Thread(target=run, daemon=True).start()
        self._poll()

    def _poll(self):
        try:
            kind, val = self.q.get_nowait()
        except queue.Empty:
            try:
                self.win.after(100, self._poll)
            except tk.TclError:
                pass
            return
        self.done(kind, val)


class FeedAssistant:
    """Type a website (or an outlet name), watch the steps, pick the feed, press Connect."""

    def __init__(self, app, prefill=""):
        self.app = app
        self.c = app.c
        w = self.win = tk.Toplevel(app.root)
        w.title("Feed assistant")
        w.configure(bg=theme.PANEL)
        w.geometry("760x560")
        w.transient(app.root)
        app.label(w, "Feed assistant", app.f_big, bg=theme.PANEL).pack(fill="x", padx=16, pady=(14, 2))
        app.label(w, "Type a website address (or the name of an outlet from the Tor list). I will look for its feed, check it "
                     "works, and connect it.", app.f_small, theme.MUTED, bg=theme.PANEL).pack(fill="x", padx=16)
        row = tk.Frame(w, bg=theme.PANEL)
        row.pack(fill="x", padx=16, pady=10)
        self.addr = tk.StringVar(value=prefill)
        e = _entry(row, self.addr, 55)
        e.pack(side="left", ipady=5)
        e.bind("<Return>", lambda ev: self.find())
        self.go = app.btn(row, "Find feed", self.find, primary=True, small=True)
        self.go.pack(side="left", padx=8)
        self.log = tk.Text(w, height=8, bg=theme.CHARCOAL, fg=theme.BONE, relief="flat", font=app.f_small, state="disabled")
        self.log.pack(fill="x", padx=16)
        app.label(w, "Feeds found", app.f_bold, bg=theme.PANEL).pack(fill="x", padx=16, pady=(10, 2))
        self.list = tk.Listbox(w, height=6, bg=theme.CHARCOAL, fg=theme.BONE, relief="flat", font=app.f_small,
                               selectbackground=theme.BLUE, selectforeground=theme.ON_BLUE, activestyle="none")
        self.list.pack(fill="x", padx=16)
        row2 = tk.Frame(w, bg=theme.PANEL)
        row2.pack(fill="x", padx=16, pady=10)
        app.label(row2, "Show it as", app.f_small, theme.MUTED, bg=theme.PANEL).pack(side="left")
        self.kind = tk.StringVar(value="news")
        ttk.Combobox(row2, textvariable=self.kind, values=["news", "military", "conflict", "hazard", "health"], width=10,
                     state="readonly").pack(side="left", padx=8)
        self.connect_btn = app.btn(row2, "Connect selected feed", self.connect, primary=True, small=True)
        self.connect_btn.pack(side="left", padx=8)
        self.result = app.label(w, "", app.f_small, theme.MUTED, bg=theme.PANEL)
        self.result.pack(fill="x", padx=16)
        self.found = []
        if prefill:
            self.find()

    def say(self, msg):
        def put():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        try:
            self.win.after(0, put)
        except tk.TclError:
            pass

    def find(self):
        text = self.addr.get().strip()
        target = outlet_home(text) or text
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.list.delete(0, "end")
        self.result.configure(text="", fg=theme.MUTED)
        try:
            discover.normalize(target)
        except ValueError as e:
            self.say(str(e))
            return
        if tor.is_onion_url(discover.normalize(target)) and not self.c.tor.proxy():
            self.say("That is a .onion address, so Tor is needed. " + self.c.tor.describe())
            return
        self.go.configure(state="disabled")
        self.say("Starting.")

        def done(kind, val):
            self.go.configure(state="normal")
            if kind == "err":
                self.say(val)
                return
            self.found = val
            for f in val:
                self.list.insert("end", f"{f['title'] or f['url']}   ({f['count']} items)   {f['url']}")
            self.list.selection_set(0)
            self.kind.set(discover.guess_kind(val[0]["url"], val[0]["title"]))
            self.say(f"Found {len(val)} working feed(s). Pick one and press Connect.")
        Worker(self.win, lambda: self.c.find_feeds(target, self.say), done)

    def connect(self):
        sel = self.list.curselection()
        if not sel:
            self.result.configure(text="Find a feed first, then pick one.", fg=theme.AMBER)
            return
        f = self.found[sel[0]]
        try:
            self.c.add_custom_feed(f["title"] or f["url"], f["url"], self.kind.get())
        except ValueError as e:
            self.result.configure(text=str(e), fg=theme.RED)
            return
        self.result.configure(text="Connected. It will be read on the next refresh.", fg=theme.GREEN)
        self.app._render_sources()
        self.app.start_refresh(force=True)


class ReaderWindow:
    """A no-script reader. Onion pages always go through Tor. Nothing on the page runs."""

    def __init__(self, app, url=""):
        self.app, self.c = app, app.c
        w = self.win = tk.Toplevel(app.root)
        w.title("Overwatch reader (no scripts)")
        w.configure(bg=theme.PANEL)
        w.geometry("980x700")
        bar = tk.Frame(w, bg=theme.PANEL)
        bar.pack(fill="x", padx=12, pady=10)
        self.addr = tk.StringVar(value=url)
        e = _entry(bar, self.addr, 80)
        e.pack(side="left", ipady=5, fill="x", expand=True)
        e.bind("<Return>", lambda ev: self.go())
        app.btn(bar, "Open", self.go, primary=True, small=True).pack(side="left", padx=6)
        self.via = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="Use Tor", variable=self.via, bg=theme.PANEL, fg=theme.BONE, selectcolor=theme.CHARCOAL,
                       activebackground=theme.PANEL, activeforeground=theme.BONE).pack(side="left")
        self.note = app.label(w, "Reader view: text and links only. No scripts, pictures or cookies. This is not Tor Browser.",
                              app.f_small, theme.MUTED, bg=theme.PANEL)
        self.note.pack(fill="x", padx=12)
        body = tk.PanedWindow(w, orient="horizontal", bg=theme.PANEL, sashwidth=4)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        self.text = tk.Text(body, wrap="word", bg=theme.CHARCOAL, fg=theme.BONE, relief="flat", font=app.f_body, state="disabled")
        body.add(self.text, stretch="always")
        self.links = tk.Listbox(body, bg=theme.CHARCOAL, fg=theme.BLUE, relief="flat", font=app.f_small, width=44,
                                activestyle="none")
        body.add(self.links)
        self.links.bind("<Double-Button-1>", self._follow)
        self.targets = []
        if url:
            self.go()

    def go(self):
        url = self.addr.get().strip()
        if "://" not in url:
            url = ("http://" if tor.is_onion_host(url.split("/")[0]) else "https://") + url
            self.addr.set(url)
        if url.lower().startswith("http://") and not tor.is_onion_url(url):
            self.note.configure(text="Plain http is only allowed for .onion addresses.", fg=theme.RED)
            return
        self.note.configure(text="Loading...", fg=theme.MUTED)

        def done(kind, val):
            if kind == "err":
                self.note.configure(text=val, fg=theme.RED)
                return
            status, html = val
            if status != 200:
                self.note.configure(text=f"Could not open it ({'HTTP ' + str(status) if status else html}).", fg=theme.RED)
                return
            title, txt, links = reader.html_to_text(html, url)
            self.win.title((title or url)[:80] + " - Overwatch reader")
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("end", (title + "\n\n" if title else "") + (txt or "(no readable text on this page)"))
            self.text.configure(state="disabled")
            self.links.delete(0, "end")
            self.targets = [u for _, u in links]
            for label, u in links:
                self.links.insert("end", label or u)
            self.note.configure(text="Reader view: text and links only. Double-click a link to follow it.", fg=theme.MUTED)
        Worker(self.win, lambda: self.c.read_page(url, self.via.get()), done)

    def _follow(self, ev):
        sel = self.links.curselection()
        if sel:
            self.addr.set(self.targets[sel[0]])
            self.go()


def build_tor_tab(app, p):
    """Settings > Tor: connection status, start/stop, onion outlets, reader."""
    c = app.c
    p.columnconfigure(0, weight=1)
    p.rowconfigure(3, weight=1)
    top = tk.Frame(p, bg=theme.PANEL)
    top.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
    app.label(top, "Tor connection", app.f_big, bg=theme.PANEL).pack(fill="x", padx=14, pady=(10, 2))
    app.tor_status = app.label(top, "", app.f_body, bg=theme.PANEL)
    app.tor_status.pack(fill="x", padx=14)
    row = tk.Frame(top, bg=theme.PANEL)
    row.pack(fill="x", padx=14, pady=8)
    app.btn(row, "Start Tor", lambda: (c.tor.bundled.start(), app._render_tor()), primary=True, small=True).pack(side="left")
    app.btn(row, "Stop Tor", lambda: (c.tor.bundled.stop(), app._render_tor()), small=True).pack(side="left", padx=8)
    app.btn(row, "Open reader", lambda: ReaderWindow(app), small=True).pack(side="left")
    app.btn(row, "Open Tor Browser", app._open_tor_browser, small=True).pack(side="left", padx=8)
    app.btn(row, "Install Tor Browser (one click)", app._install_tor_browser, small=True).pack(side="left")
    tk.Label(top, justify="left", anchor="w", wraplength=980, font=app.f_small, fg=theme.MUTED, bg=theme.PANEL,
             text=("Overwatch carries its own Tor for reading feeds and pages. For browsing, it installs the real Tor Browser from the "
                   "Tor Project (checked against their checksum) and opens it for you. That is the only browser built to hide you "
                   "on Tor, so Overwatch does not try to imitate one. The quick text reader is not Tor Browser.")).pack(fill="x", padx=14, pady=(0, 10))
    app.label(p, "Outlets reported to run an official onion service", app.f_big).grid(row=1, column=0, sticky="w", padx=16)
    app.label(p, "No onion addresses are built in. Press Look up to read the address from the outlet's own website, "
                 "then Connect to add its feed.", app.f_small, theme.MUTED).grid(row=2, column=0, sticky="w", padx=16)
    app.onion_tree = ttk.Treeview(p, columns=("site", "onion"), show="tree headings", height=9)
    for col, text, w in (("#0", "Outlet", 240), ("site", "Website", 260), ("onion", "Onion address", 520)):
        app.onion_tree.heading(col, text=text)
        app.onion_tree.column(col, width=w, anchor="w")
    app.onion_tree.grid(row=3, column=0, sticky="nsew", padx=14, pady=6)
    row2 = tk.Frame(p, bg=theme.CHARCOAL)
    row2.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 6))
    app.btn(row2, "Look up onion address", app._lookup_onion, small=True).pack(side="left")
    app.btn(row2, "Connect its feed (normal site)", lambda: app._outlet_feed(False), small=True).pack(side="left", padx=8)
    app.btn(row2, "Connect its feed (via Tor)", lambda: app._outlet_feed(True), small=True).pack(side="left")
    app.btn(row2, "Open in reader", app._outlet_reader, small=True).pack(side="left", padx=8)
    app.tor_note = app.label(p, "", app.f_small, theme.MUTED)
    app.tor_note.grid(row=5, column=0, sticky="w", padx=16, pady=(0, 10))


def open_tor_browser(url="", root=""):
    exe = tor.find_tor_browser(root)
    if not exe:
        return False
    try:
        subprocess.Popen([exe] + ([url] if url else []))
        return True
    except OSError:
        return False
