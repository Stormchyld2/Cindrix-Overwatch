"""Drives the real window on CI (Windows). Run: python -m tests.smoke_ui"""

import tempfile
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

        app.root.destroy()
        c.close()
    print("smoke ui OK")


if __name__ == "__main__":
    main()
