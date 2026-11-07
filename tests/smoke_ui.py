"""Drives the real window on CI (Windows). Run: python -m tests.smoke_ui"""

import tempfile
import tkinter as tk
import time

from cindrix_overwatch import engine
from cindrix_overwatch.ui import App
from tests import samples as S


def fetch(url):
    if "usgs" in url:
        return 200, S.USGS
    if "weather.gov" in url:
        return 200, S.NWS
    if "bbci" in url:
        return 200, S.NEWS_RSS
    if "swpc" in url:
        return 200, S.SWPC
    if "gdelt" in url and "airstrike" in url:
        return 200, S.GDELT
    return 503, ""


def pump(app, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        time.sleep(0.01)


def wait_refresh(app):
    end = time.time() + 20
    while time.time() < end and (app.worker.is_alive() or not app.q.empty()):
        pump(app, 0.1)
    pump(app, 0.4)


def main():
    with tempfile.TemporaryDirectory() as d:
        # the fake clock is the sample clock so the sample items count as recent
        c = engine.Controller(d, fetch, lambda: S.NOW)
        c.host_gaps = {}
        app = App(controller=c, splash=False, auto=False)
        pump(app)
        assert len(app.tiles) == 9
        assert app.start_refresh(force=True)
        wait_refresh(app)
        assert c.store.count() > 5, c.store.count()
        assert len(app.feed_inner.winfo_children()) >= 5, "feed cards missing"
        assert any(it.pinned for it in app.map.items), "no pins on the map"
        assert app.map._hits, "no clickable pins were drawn"

        # clicking a pin selects it and shows it in the card
        x, y, it = app.map._hits[0]
        assert app.map.pick(x, y) is it
        assert it.title[:20] in app.sel_title.cget("text")

        # feed filter chips and search
        app._set_filter(("Military", {"military"}))
        pump(app)
        assert all(i.kind == "military" for i in app.feed_items), [i.kind for i in app.feed_items]
        app._set_filter(("All", None))
        app.search.set("missile")
        pump(app)
        assert app.feed_items and all("missile" in i.title.lower() for i in app.feed_items)
        app.search.set("")

        # layers, zoom, pan, reset
        app._toggle_layer("conflict")
        app.map.zoom_by(1.5)
        app.map.reset_view()
        app._center_home()
        pump(app)

        # every page opens
        for page in ("brief", "settings", "war"):
            app.show_page(page)
            pump(app, 0.1)
        assert "Status lights" in app.brief_text.get("1.0", "end")
        # the Intel dashboard: status lights, the Top 10, the channel panels, then into the reader and back
        app.show_page("intel")
        pump(app, 0.2)
        intel = app.intel
        assert intel.mode == "dash"
        assert intel.d_tiles[0][2].cget("text"), "dashboard status lights empty"
        assert intel.d_top.winfo_children(), "Top 10 panel empty"
        assert any(b.winfo_children() for b in intel.d_panels.values()), "channel panels empty"
        # the where / how serious filters re-draw the dashboard and the list without errors
        for region, sev in (("Europe", "Any severity"), ("Everywhere", "Warning and up"), ("Near home (1000 km)", "Severe only")):
            intel.region_var.set(region)
            intel.sev_var.set(sev)
            pump(app, 0.1)
        intel.region_var.set("Everywhere")
        intel.sev_var.set("Any severity")
        pump(app, 0.1)
        first = c.top_warnings(10)
        assert first, "no early warning items"
        intel.go_reading(None, first[0][0])
        pump(app, 0.2)
        assert intel.mode == "reading"
        assert first[0][0].shown in intel.r_title.cget("text")
        intel.go_dash()
        pump(app, 0.2)
        assert intel.mode == "dash"
        app.show_page("settings")
        assert len(app.feed_rows) >= 15, len(app.feed_rows)
        assert len(app.onion_tree.get_children()) >= 8
        assert app.tor_status.cget("text")
        app.settings_tabs.select(2)
        pump(app, 0.1)
        app.settings_tabs.select(3)
        pump(app, 0.1)
        assert "Cindrix folder" in app.ai_status.cget("text") or "No Cindrix folder" in app.ai_status.cget("text")
        assert "early warning" in app.ai_instr.get("1.0", "end") or "emergency" in app.ai_instr.get("1.0", "end")
        assert app.c.settings["auto_translate"] is True and app.ai_auto_var.get() is True
        app.show_page("brief")
        assert str(app.ai_brief_btn.cget("state")) == "disabled"

        # settings: bad and good home states, custom feed
        app.home_var.set("ZZ")
        app._save_home()
        assert "state code" in app.home_note.cget("text")
        app.home_var.set("WV, TN")
        app._save_home()
        wait_refresh(app)
        app.cf_name.set("Mine")
        app.cf_url.set("http://not-secure.example.com/rss")
        app._add_feed()
        assert "https" in app.src_note.cget("text")
        app.cf_url.set("https://example.com/feed.xml")
        app._add_feed()
        wait_refresh(app)
        assert len(c.settings["custom_feeds"]) == 1
        assert "custom-0" in app.feed_rows, "a new feed must get its own switch in Settings"
        # every feed has a switch: flip one off and on again
        app._flip_source("usgs", False)
        assert "usgs" in c.settings["disabled"]
        app._flip_source("usgs", True)
        assert "usgs" not in c.settings["disabled"]
        app._remove_feed(0)
        assert "custom-0" not in app.feed_rows and not c.settings["custom_feeds"]

        # Watchtower settings: add, switch, remove, and the supported-cameras window
        app.wt_name.set("Front door"); app.wt_host.set("rtsp://192.168.1.20:554/stream1")
        from cindrix_overwatch import ui_cameras
        ui_cameras._add(app, [b for b in __import__("cindrix_overwatch.cameras", fromlist=["x"]).brands() if b["tier"] != "no"])
        assert len(c.cameras()) == 1 and len(app.wt_rows) == 1, "camera must appear with its own switch"
        cid = c.cameras()[0]["id"]
        ui_cameras._flip(app, cid, False)
        assert c.cameras()[0]["enabled"] is False
        win = ui_cameras.SupportedWindow(app)
        win.root_children = len(win.inner.winfo_children())
        assert win.root_children >= 20, win.root_children
        win.search.set("reolink")
        assert len(win.inner.winfo_children()) == 1
        win.close()
        ui_cameras._remove(app, cid)
        assert not c.cameras()

        # phone link: switching it on opens the sync page and makes a code; switching off closes it
        from cindrix_overwatch import link as _lk
        app.link_on.set(True)
        ui_cameras.link_toggle(app)
        assert app.link_server is not None and _lk.parse_code(app.link_code_var.get()), app.link_code_var.get()
        old_code = app.link_code_var.get()
        ui_cameras.link_new_code(app)
        assert app.link_code_var.get() != old_code
        app.link_on.set(False)
        ui_cameras.link_toggle(app)
        assert app.link_server is None and not app.link_code_var.get()

        # DEFCON chips show on every screen but Settings
        app.show_page("war")
        assert "DEFCON" in app.defcon_est.cget("text")
        assert app.defcon_box.winfo_ismapped(), "DEFCON must show on the war room"
        app.show_page("settings")
        app.root.update_idletasks()
        assert not app.defcon_box.winfo_ismapped(), "DEFCON must be hidden on Settings"
        app.show_page("intel")
        app.root.update_idletasks()
        assert app.defcon_box.winfo_ismapped(), "DEFCON must come back on Intel"
        app.show_page("settings")

        # the DEFCON guide opens from General settings and lists all five levels
        before = set(app.root.winfo_children())
        app.show_defcon_guide()
        new = [w for w in app.root.winfo_children() if w not in before]
        assert len(new) == 1 and new[0].title() == "What the DEFCON levels mean"
        new[0].destroy()

        # lock: needs a PIN first, then covers the tab until the right PIN is typed
        app.lock_mode.set("pin")
        ui_cameras.lock_apply(app)
        assert app.lock_mode.get() == "off", "lock cannot be switched on before a PIN exists"
        app.pin1.set("2468"); app.pin2.set("2468")
        ui_cameras.lock_save_pin(app)
        app.lock_mode.set("pin")
        ui_cameras.lock_apply(app)
        assert c.lock()["mode"] == "pin"
        assert not app.nav["watchtower"].winfo_ismapped(), "the Watchtower tab must be hidden until switched on"
        app.wt_on.set(True)
        c.set_watchtower_on(True); app.apply_watchtower_tab()
        app.root.update()
        assert app.nav["watchtower"].winfo_ismapped(), "the Watchtower tab must show once switched on"
        app.show_page("watchtower")
        assert app.watchtower.lock_ui is not None and not app.watchtower.visible, "Watchtower must start locked"
        app.watchtower.pin_var.set("0000")
        app.watchtower._try_pin()
        assert app.watchtower.lock_ui is not None, "a wrong PIN must not unlock"
        app.watchtower.pin_var.set("2468")
        app.watchtower._try_pin()
        assert app.watchtower.lock_ui is None and app.watchtower.visible, "the right PIN unlocks"
        app.lock_mode.set("off")
        ui_cameras.lock_apply(app)
        app.show_page("settings")

        # Watchtower viewer: tiles, offline screen, dock picker, modes (live pictures only when ffmpeg is here)
        import os, subprocess, tempfile as _tf
        from cindrix_overwatch import camview
        wt = app.watchtower
        for n in range(6):
            c.settings["cameras"].append({"id": f"c{n}", "name": f"Cam {n}", "brand": "other", "main": "/nonexistent.mp4", "sub": "",
                                          "user": "", "password": "", "enabled": True})
        ff = camview.find_ffmpeg()
        clip = os.path.join(d, "clip.mp4")
        if ff:
            subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "40", "-pix_fmt", "yuv420p",
                            "-c:v", "libx264", clip], check=True)
            c.settings["cameras"][0]["main"] = clip
        c.save_settings()
        app.show_page("watchtower")
        wt.refresh()
        assert len(wt.tiles) == 4 and wt.mode == 4, "Watchtower opens on the 4-camera view"
        app.root.update()
        end = time.time() + (6 if ff else 2)
        while time.time() < end:
            app.root.update()
            time.sleep(0.05)
        if ff:
            assert wt.tiles[0].drawn == "frame", ("live picture must show", wt.tiles[0].drawn)
        assert wt.tiles[1].drawn.startswith("off:"), ("an unreachable camera must show the offline screen", wt.tiles[1].drawn)
        wt._place(tk.Toplevel(app.root), "c3", 1)
        assert wt.slots[1] == "c3" and wt.slots[3] == "c1", wt.slots
        wt.set_mode(6)
        assert len(wt.tiles) == 6
        wt.set_mode(1)
        assert len(wt.tiles) == 1
        wt.list_clicked("c2")
        assert wt.one == "c2"
        wt.set_mode(4)
        app.show_page("settings")
        assert not wt.feeds, "feeds stop when the tab is left"
        for n in range(6):
            c.remove_camera(f"c{n}")


        app.root.destroy()
        c.close()
    print("smoke ui OK")


if __name__ == "__main__":
    main()
