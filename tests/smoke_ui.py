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
        assert len(app.tiles) == 8
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
        app.show_page("settings")
        assert len(app.tree.get_children()) >= 15, len(app.tree.get_children())
        assert len(app.onion_tree.get_children()) >= 8
        assert app.tor_status.cget("text")
        app.settings_tabs.select(2)
        pump(app, 0.1)

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

        app.root.destroy()
        c.close()
    print("smoke ui OK")


if __name__ == "__main__":
    main()
