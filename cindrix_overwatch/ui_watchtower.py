"""The Watchtower tab: live cameras in a 4-up or 6-up grid or one at a time, a scrolling list of every camera on the left,
a dock picker to say where a camera goes, an offline screen, and recording."""

import threading
import time
import tkinter as tk

from . import camview, cameras, theme

MODES = [("4 cameras", 4), ("6 cameras", 6), ("One camera", 1)]
GRID = {4: (2, 2), 6: (2, 3), 1: (1, 1)}
TICK_MS = 120


class Tile:
    """One picture area. It shows the camera's newest frame, the offline screen, or an empty dock."""

    def __init__(self, page, parent, dock):
        self.page, self.dock = page, dock
        self.cam_id = None
        self.seq = -1
        self.drawn = ""
        self.photo = None
        self.cv = tk.Canvas(parent, bg="#000000", highlightthickness=0, cursor="hand2")
        self.cv.bind("<Button-1>", lambda e: page.tile_clicked(self))
        self.cv.bind("<Configure>", lambda e: page.layout_changed())

    def size(self):
        return max(self.cv.winfo_width(), 2), max(self.cv.winfo_height(), 2)

    def clear(self):
        self.cv.delete("all")
        self.photo = None
        self.drawn = ""
        self.seq = -1

    def tag(self, text, rec, live):
        w, _h = self.size()
        self.cv.delete("tag")
        x = 10
        self.cv.create_rectangle(x - 6, 8, x + 18 + 7 * len(text) + (46 if rec else 0), 32, fill="#0f1113", outline="", tags="tag")
        self.cv.create_oval(x, 15, x + 9, 24, fill=theme.RED if (rec or not live) else theme.GREEN, outline="", tags="tag")
        self.cv.create_text(x + 16, 20, text=text + ("  REC" if rec else ""), anchor="w", fill=theme.BONE, font=self.page.app.f_small, tags="tag")

    def show_empty(self):
        if self.drawn == "empty":
            return
        self.clear()
        w, h = self.size()
        self.cv.create_text(w // 2, h // 2, text=f"Dock {self.dock + 1}\nPick a camera from the list", fill=theme.MUTED,
                            font=self.page.app.f_body, justify="center")
        self.drawn = "empty"

    def show_offline(self, name, rec):
        key = f"off:{name}:{rec}"
        w, h = self.size()
        if self.drawn == key + f":{w}x{h}":
            return
        self.clear()
        cx, cy = w // 2, h // 2 - 8
        c = "#a9b0b6"
        r = max(10, min(w, h) // 12)
        # an eye with a line through it
        self.cv.create_oval(cx - 2 * r, cy - r, cx + 2 * r, cy + r, outline=c, width=2)
        self.cv.create_oval(cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2, outline=c, width=2)
        self.cv.create_line(cx - 2 * r - 6, cy - r - 6, cx + 2 * r + 6, cy + r + 6, fill=c, width=3)
        self.cv.create_text(cx, cy + r + 24, text="Camera is offline...", fill=c, font=self.page.app.f_body)
        self.tag(name, rec, False)
        self.drawn = key + f":{w}x{h}"

    def show_frame(self, feed, name, rec):
        try:
            img = tk.PhotoImage(data=feed.frame, format="ppm")
        except tk.TclError:
            return
        w, h = self.size()
        self.cv.delete("all")
        self.photo = img
        self.cv.create_image(w // 2, h // 2, image=img)
        self.seq = feed.seq
        self.tag(name, rec, True)
        self.drawn = "frame"


class WatchtowerPage:
    def __init__(self, app, parent):
        self.app = app
        self.c = app.c
        self.parent = parent
        self.cams = {}
        self.feeds = {}
        self.recs = {}
        self.want_rec = set()
        self.reach = {}
        self.visible = False
        self.tiles = []
        self.row_widgets = {}
        self._layout_after = None
        self._last_rec_check = 0.0
        self._ticking = False
        self._stop_probe = threading.Event()
        w = self.c.watchtower()
        self.mode, self.slots, self.one = w["mode"], w["slots"], w["one"]
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self._build_bar()
        body = tk.Frame(parent, bg=theme.CHARCOAL)
        body.grid(row=1, column=0, sticky="nsew", padx=14)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_side(body)
        self.grid_area = tk.Frame(body, bg=theme.CHARCOAL)
        self.grid_area.grid(row=0, column=1, sticky="nsew")
        self.strip = tk.Frame(parent, bg=theme.PANEL)
        self.strip.grid(row=2, column=0, sticky="ew", padx=14, pady=(10, 14))
        self.app.label(self.strip, "RECENT ALERTS", self.app.f_head, theme.BLUE, bg=theme.PANEL).pack(anchor="w", padx=14, pady=(10, 2))
        self.alerts_box = tk.Frame(self.strip, bg=theme.PANEL)
        self.alerts_box.pack(fill="x", padx=14, pady=(0, 10))
        self.refresh()
        threading.Thread(target=lambda: camview.prune_recordings(camview.recordings_root(), self.c.watchtower()["keep_days"]), daemon=True).start()
        threading.Thread(target=self._probe_loop, daemon=True).start()

    # ----- layout -----
    def _build_bar(self):
        a = self.app
        bar = tk.Frame(self.parent, bg=theme.CHARCOAL)
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        a.label(bar, "WATCHTOWER", a.f_title).pack(side="left")
        self.note = a.label(bar, "", a.f_small, theme.AMBER)
        self.note.pack(side="left", padx=14)
        self.rec_btn = tk.Button(bar, text="Record all shown", relief="flat", bd=0, padx=12, pady=5, font=a.f_small, cursor="hand2",
                                 bg=theme.PANEL_HIGH, fg=theme.BONE, command=self.toggle_rec_all)
        self.rec_btn.pack(side="right", padx=(8, 0))
        self.seg = tk.Frame(bar, bg=theme.PANEL)
        self.seg.pack(side="right")
        self.seg_btns = {}
        for text, m in MODES:
            b = tk.Button(self.seg, text=text, relief="flat", bd=0, padx=12, pady=5, font=a.f_small, cursor="hand2", command=lambda m=m: self.set_mode(m))
            b.pack(side="left", padx=2, pady=2)
            self.seg_btns[m] = b

    def _build_side(self, body):
        side = tk.Frame(body, bg=theme.PANEL, width=240)
        side.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        side.grid_propagate(False)
        side.rowconfigure(1, weight=1)
        side.columnconfigure(0, weight=1)
        self.app.label(side, "CAMERAS CONNECTED", self.app.f_head, theme.MUTED, bg=theme.PANEL).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        self.side_cv = tk.Canvas(side, bg=theme.PANEL, highlightthickness=0, width=220)
        self.side_cv.grid(row=1, column=0, sticky="nsew", padx=(6, 0))
        self.side_in = tk.Frame(self.side_cv, bg=theme.PANEL)
        self.side_win = self.side_cv.create_window(0, 0, window=self.side_in, anchor="nw")
        self.side_in.bind("<Configure>", lambda e: self.side_cv.configure(scrollregion=self.side_cv.bbox("all")))
        self.side_cv.bind("<Configure>", lambda e: self.side_cv.itemconfigure(self.side_win, width=e.width))
        # the mouse wheel scrolls the list; there is no scroll bar
        for w in (self.side_cv, self.side_in):
            w.bind("<Enter>", lambda e: self.side_cv.bind_all("<MouseWheel>", self._wheel))
            w.bind("<Leave>", lambda e: self.side_cv.unbind_all("<MouseWheel>"))
        self.scan_btn = tk.Button(side, text="Scan network again", relief="flat", bd=0, font=self.app.f_small, cursor="hand2",
                                  bg=theme.PANEL, fg=theme.MUTED, anchor="w", padx=12, pady=8, command=self.scan)
        self.scan_btn.grid(row=2, column=0, sticky="ew")

    def _wheel(self, e):
        if self.side_in.winfo_height() > self.side_cv.winfo_height():
            self.side_cv.yview_scroll(-1 if e.delta > 0 else 1, "units")

    # ----- data -----
    def refresh(self):
        """Re-reads the camera list (called after anything changes it) and redraws."""
        self.cams = {c["id"]: c for c in self.c.cameras() if c.get("enabled", True)}
        self._fix_slots()
        for cid in list(self.recs):
            if cid not in self.cams:
                self.recs.pop(cid).stop()
                self.want_rec.discard(cid)
        if self.one not in self.cams:
            self.one = next(iter(self.cams), "")
        self.rebuild_grid()
        self.render_list()
        self.render_alerts()

    def _fix_slots(self):
        slots = [s if s in self.cams else "" for s in (self.slots + [""] * 6)[:6]]
        used = {s for s in slots if s}
        spare = [i for i in self.cams if i not in used]
        slots = [s or (spare.pop(0) if spare else "") for s in slots]
        self.slots = slots

    def _save(self):
        self.c.set_watchtower(mode=self.mode, slots=self.slots, one=self.one)

    def shown_ids(self):
        if self.mode == 1:
            return [self.one] if self.one else []
        return [s for s in self.slots[:self.mode] if s]

    def _probe_loop(self):
        while not self._stop_probe.is_set():
            for cid, cam in list(self.cams.items()):
                self.reach[cid] = camview.reachable(cameras.stream_address(cam))
            self._stop_probe.wait(20)

    def is_online(self, cid):
        f = self.feeds.get(cid)
        if f and f.state == "live":
            return True
        if f and f.state == "offline":
            return False
        return self.reach.get(cid, True)

    # ----- the grid -----
    def rebuild_grid(self):
        for t in self.tiles:
            t.cv.destroy()
        self.tiles = []
        rows, cols = GRID[self.mode]
        for i in range(6):
            self.grid_area.rowconfigure(i, weight=0, uniform="")
            self.grid_area.columnconfigure(i, weight=0, uniform="")
        for r in range(rows):
            self.grid_area.rowconfigure(r, weight=1, uniform="r")
        for c in range(cols):
            self.grid_area.columnconfigure(c, weight=1, uniform="c")
        n = 1 if self.mode == 1 else self.mode
        for i in range(n):
            t = Tile(self, self.grid_area, i)
            t.cv.grid(row=i // cols, column=i % cols, sticky="nsew", padx=3, pady=3)
            t.cam_id = self.one if self.mode == 1 else self.slots[i]
            self.tiles.append(t)
        for m, b in self.seg_btns.items():
            b.configure(bg=theme.BLUE if m == self.mode else theme.PANEL, fg=theme.ON_BLUE if m == self.mode else theme.BONE)
        self._update_rec_button()
        self.sync_feeds()

    def layout_changed(self):
        if self._layout_after:
            self.parent.after_cancel(self._layout_after)
        self._layout_after = self.parent.after(350, self.sync_feeds)

    def sync_feeds(self):
        """Runs a feed for each camera on screen (small stream in the grid, full stream when alone) and stops the rest."""
        self._layout_after = None
        want = {}
        if self.visible:
            for t in self.tiles:
                if t.cam_id in self.cams:
                    w, _h = t.size()
                    want[t.cam_id] = (self.mode == 1, min(1280 if self.mode == 1 else 640, max(w, 160)))
        for cid in list(self.feeds):
            if cid not in want:
                self.feeds.pop(cid).stop()
        for cid, (single, width) in want.items():
            cam = self.cams[cid]
            fn = (lambda cam=cam, sub=not single: cameras.stream_address(cam, sub=sub))
            f = self.feeds.get(cid)
            if f is None:
                f = self.feeds[cid] = camview.Feed(fn, width=width, fps=10 if single else 8)
                f.single = single
                f.start()
            elif getattr(f, "single", None) != single or abs(f.width - width) > 0.15 * f.width:
                f.single = single
                f.reconfigure(fn, width=width, fps=10 if single else 8)

    def tick(self):
        if not self.visible:
            self._ticking = False
            return
        self._ticking = True
        for t in self.tiles:
            cam = self.cams.get(t.cam_id)
            if not cam:
                t.show_empty()
                continue
            rec = t.cam_id in self.recs and self.recs[t.cam_id].active
            f = self.feeds.get(t.cam_id)
            if f is None:
                continue
            if f.state == "live" and f.frame is not None:
                if f.seq != t.seq or t.drawn != "frame":
                    t.show_frame(f, cam["name"], rec)
                elif rec != getattr(t, "rec_shown", rec):
                    t.tag(cam["name"], rec, True)
                t.rec_shown = rec
            elif f.state == "offline":
                t.show_offline(cam["name"], rec)
        now = time.monotonic()
        if now - self._last_rec_check > 5:
            self._last_rec_check = now
            self._resume_recordings()
            self.render_list(light=True)
        self.parent.after(TICK_MS, self.tick)

    # ----- the camera list -----
    def render_list(self, light=False):
        shown = self.shown_ids()
        sig = tuple((cid, self.is_online(cid), cid in shown, cid in self.want_rec, self.slot_of(cid)) for cid in self.cams)
        if light and sig == getattr(self, "_list_sig", None):
            return
        self._list_sig = sig
        for w in self.side_in.winfo_children():
            w.destroy()
        a = self.app
        if not self.cams:
            a.label(self.side_in, "No cameras yet.\nAdd one in Settings > Watchtower.", a.f_small, theme.MUTED, bg=theme.PANEL,
                    justify="left").pack(anchor="w", padx=8, pady=8)
        for cid, cam in self.cams.items():
            on = self.is_online(cid)
            row = tk.Frame(self.side_in, bg=theme.PANEL_HIGH if cid in shown else theme.PANEL, cursor="hand2")
            row.pack(fill="x", pady=1)
            dot = tk.Canvas(row, width=12, height=12, bg=row["bg"], highlightthickness=0)
            dot.create_oval(2, 2, 10, 10, fill=theme.GREEN if on else theme.RED, outline="")
            dot.pack(side="left", padx=(8, 4), pady=10)
            info = tk.Frame(row, bg=row["bg"])
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=cam["name"], font=a.f_bold, fg=theme.BONE, bg=row["bg"], anchor="w").pack(fill="x")
            slot = self.slot_of(cid)
            sub = ("Offline" if not on else cameras.host_label(cam)) + (f"  ·  dock {slot}" if slot and self.mode != 1 else "")
            tk.Label(info, text=sub, font=a.f_small, fg=theme.MUTED, bg=row["bg"], anchor="w").pack(fill="x")
            rb = tk.Button(row, text="Stop" if cid in self.want_rec else "Rec", relief="flat", bd=0, padx=8, pady=2, font=a.f_small, cursor="hand2",
                           bg=theme.RED if cid in self.want_rec else theme.CHARCOAL, fg="#ffffff" if cid in self.want_rec else theme.BONE,
                           state="normal" if on or cid in self.want_rec else "disabled", command=lambda i=cid: self.toggle_rec(i))
            rb.pack(side="right", padx=6)
            for w in (row, dot, info, *info.winfo_children()):
                w.bind("<Button-1>", lambda e, i=cid: self.list_clicked(i))

    def slot_of(self, cid):
        if self.mode == 1:
            return 0
        try:
            return self.slots[:self.mode].index(cid) + 1
        except ValueError:
            return 0

    def list_clicked(self, cid):
        if self.mode == 1:
            self.one = cid
            self._save()
            self.rebuild_grid()
            self.render_list()
        else:
            self.pick_dock(cid)

    def tile_clicked(self, tile):
        if self.mode != 1 and tile.cam_id in self.cams and self.is_online(tile.cam_id):
            self.mode, self.one = 1, tile.cam_id
            self._save()
            self.rebuild_grid()
            self.render_list()
        elif tile.cam_id not in self.cams:
            self.note.configure(text="Pick a camera from the list on the left.", fg=theme.MUTED)

    def set_mode(self, m):
        if m == self.mode:
            return
        self.mode = m
        if m == 1 and not self.one:
            self.one = next(iter(self.shown_ids()), next(iter(self.cams), ""))
        self._save()
        self.rebuild_grid()
        self.render_list()

    # ----- the dock picker -----
    def pick_dock(self, cid):
        a = self.app
        w = tk.Toplevel(a.root)
        w.title("Select a dock")
        w.configure(bg=theme.PANEL)
        w.transient(a.root)
        w.resizable(False, False)
        w.attributes("-topmost", True)
        name = self.cams[cid]["name"]
        tk.Label(w, text=f"Select the dock for {name}", font=a.f_head, fg=theme.BONE, bg=theme.PANEL).pack(padx=20, pady=(18, 4))
        tk.Label(w, text="Click the number where you want this feed. It replaces the camera that is there now.", font=a.f_small, fg=theme.MUTED,
                 bg=theme.PANEL, wraplength=340, justify="center").pack(padx=20)
        rows, cols = GRID[self.mode]
        g = tk.Frame(w, bg=theme.PANEL)
        g.pack(padx=20, pady=14)
        for i in range(self.mode):
            there = self.cams.get(self.slots[i], {}).get("name", "empty")
            b = tk.Button(g, text=f"{i + 1}\n{there}", width=12, height=3, relief="flat", bd=0, font=a.f_small, bg=theme.CHARCOAL, fg=theme.BONE,
                          cursor="hand2", command=lambda k=i: self._place(w, cid, k))
            b.grid(row=i // cols, column=i % cols, padx=3, pady=3)
        a.btn(w, "Cancel", w.destroy, small=True).pack(anchor="e", padx=20, pady=(0, 14))
        self._front(w)

    def _front(self, w):
        """Brings a pop-up in front of the app and keeps it there until it is answered."""
        w.update_idletasks()
        a = self.app.root
        x = a.winfo_rootx() + (a.winfo_width() - w.winfo_width()) // 2
        y = a.winfo_rooty() + (a.winfo_height() - w.winfo_height()) // 2
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        w.lift()
        w.focus_force()
        try:
            w.grab_set()
        except tk.TclError:
            pass

    def _place(self, win, cid, k):
        at = self.slots.index(cid) if cid in self.slots else -1
        if at >= 0 and at != k:
            self.slots[at] = self.slots[k]
        self.slots[k] = cid
        win.destroy()
        self._save()
        self.rebuild_grid()
        self.render_list()

    # ----- recording -----
    def _recorder(self, cid):
        cam = self.cams[cid]
        if cid not in self.recs:
            self.recs[cid] = camview.Recorder(camview.recordings_root(), cam["name"], lambda cam=cam: cameras.stream_address(cam))
        return self.recs[cid]

    def toggle_rec(self, cid):
        if cid in self.want_rec:
            self.want_rec.discard(cid)
            if cid in self.recs:
                self.recs[cid].stop()
        else:
            if not camview.find_ffmpeg():
                self.note.configure(text="The video part of Overwatch is missing, so it cannot record.", fg=theme.RED)
                return
            if camview.low_disk(camview.recordings_root()):
                self.note.configure(text="Less than 2 GB free on this drive. Free some space first.", fg=theme.RED)
                return
            if self._recorder(cid).start():
                self.want_rec.add(cid)
                self.note.configure(text="Recording to Downloads/Cindrix/Cameras", fg=theme.MUTED)
            else:
                self.note.configure(text="Could not start recording: " + self.recs[cid].error, fg=theme.RED)
        self._update_rec_button()
        self.render_list()

    def toggle_rec_all(self):
        ids = self.shown_ids()
        any_on = any(i in self.want_rec for i in ids)
        for i in ids:
            if any_on == (i in self.want_rec):
                self.toggle_rec(i)

    def _update_rec_button(self):
        ids = self.shown_ids()
        on = any(i in self.want_rec for i in ids)
        self.rec_btn.configure(bg=theme.RED if on else theme.PANEL_HIGH, fg="#ffffff" if on else theme.BONE,
                               text="Stop recording" if on else ("Record this camera" if self.mode == 1 else "Record all shown"))

    def _resume_recordings(self):
        """A recording that stopped because the camera dropped starts again when the camera is back."""
        for cid in list(self.want_rec):
            r = self.recs.get(cid)
            if r and not r.active and self.reach.get(cid, False):
                r.start()
        self._update_rec_button()

    # ----- scan and alerts -----
    def scan(self):
        fn = getattr(self.app, "scan_for_cameras", None)
        if fn:
            fn()

    def render_alerts(self):
        for w in self.alerts_box.winfo_children():
            w.destroy()
        items = self.c.camera_alerts(5) if hasattr(self.c, "camera_alerts") else []
        if not items:
            self.app.label(self.alerts_box, "No alerts yet. Alerts for people and vehicles will show here.", self.app.f_small, theme.MUTED,
                           bg=theme.PANEL).pack(anchor="w")
        for it in items:
            line = tk.Frame(self.alerts_box, bg=theme.PANEL)
            line.pack(fill="x")
            self.app.label(line, it.get("when", ""), self.app.f_small, theme.MUTED, bg=theme.PANEL, width=10, anchor="w").pack(side="left")
            self.app.label(line, it.get("text", ""), self.app.f_small, theme.BONE, bg=theme.PANEL).pack(side="left")

    # ----- show / hide -----
    def show(self):
        self.visible = True
        self.refresh()
        self.sync_feeds()
        if not self._ticking:
            self.tick()

    def hide(self):
        self.visible = False
        for f in self.feeds.values():
            f.stop()
        self.feeds = {}

    def shutdown(self):
        self.hide()
        self._stop_probe.set()
        for cid in list(self.recs):
            self.recs[cid].stop()
