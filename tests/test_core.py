import os
import tempfile
import threading
import unittest

from cindrix_overwatch import engine, feeds, geo, scoring, sources
from cindrix_overwatch.model import Item
from cindrix_overwatch.store import Store
from tests import samples as S

SRC = {"id": "t", "name": "Test", "kind": "news", "trust": "wire"}


class FeedParsers(unittest.TestCase):
    def test_rss_and_pinning(self):
        items = feeds.parse_rss(S.NEWS_RSS, SRC, S.NOW)
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0].place, "Ukraine")
        self.assertTrue(items[0].pinned)
        self.assertEqual(items[2].place, "Baltic Sea")
        self.assertFalse(items[3].pinned)

    def test_atom(self):
        items = feeds.parse_rss(S.ATOM_MOD, SRC, S.NOW)
        self.assertEqual(items[0].url, "https://www.gov.uk/x")
        self.assertAlmostEqual(items[0].ts, S.NOW - 4000, delta=1)

    def test_dtd_refused_and_garbage(self):
        with self.assertRaises(feeds.FeedError):
            feeds.parse_rss(S.EVIL_XML, SRC)
        with self.assertRaises(feeds.FeedError):
            feeds.parse_rss("<html><body>blocked</body></html>", SRC)
        with self.assertRaises(feeds.FeedError):
            feeds.parse_rss("not xml at all", SRC)

    def test_link_must_be_http(self):
        x = S.rss([("Title here", "javascript:alert(1)", "", S.NOW)])
        self.assertEqual(feeds.parse_rss(x, SRC)[0].url, "")

    def test_usgs(self):
        items = feeds.parse_usgs(S.USGS, {"id": "usgs", "name": "USGS"}, S.NOW)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].severity, 2)
        self.assertEqual((items[0].lat, items[0].lon), (38.0, 142.0))
        with self.assertRaises(feeds.FeedError):
            feeds.parse_usgs("<html>", {"id": "u", "name": "u"})

    def test_nws(self):
        items = feeds.parse_nws(S.NWS, {"id": "nws-wv", "name": "NWS"}, S.NOW)
        self.assertEqual(items[0].states, ["WV"])
        self.assertTrue(items[0].pinned)           # no polygon: falls back to the state centre
        self.assertEqual(items[1].severity, 3)
        self.assertAlmostEqual(items[1].lat, 36.0, 1)

    def test_eonet_gdacs_swpc_gdelt(self):
        e = feeds.parse_eonet(S.EONET, {"id": "eonet", "name": "E"}, S.NOW)
        self.assertEqual((e[0].lat, e[0].lon), (38.0, -120.0))
        g = feeds.parse_gdacs(S.GDACS, {"id": "gdacs", "name": "G"}, S.NOW)
        self.assertEqual((g[0].severity, g[0].lat, g[0].lon), (2, 15.5, 120.1))
        sw = feeds.parse_swpc(S.SWPC, {"id": "swpc", "name": "N"}, S.NOW)
        self.assertEqual({i.title.split(":")[0] for i in sw}, {"Geomagnetic storm", "Radio blackout"})
        d = feeds.parse_gdelt(S.GDELT, {"id": "gd", "name": "GDELT", "kind": "conflict"}, S.NOW)
        self.assertEqual(d[0].place, "Gaza")          # from the headline, not the outlet's country
        with self.assertRaises(feeds.FeedError):
            feeds.parse_gdelt("Your query was too short", {"id": "gd", "name": "G", "kind": "news"})

    def test_time_formats(self):
        self.assertEqual(feeds.parse_time("20271231T120000Z"), feeds.parse_time("2027-12-31T12:00:00Z"))
        self.assertIsNone(feeds.parse_time("garbage"))


class Geo(unittest.TestCase):
    def test_places_and_states(self):
        self.assertEqual(geo.find_place("Warship near Taiwan Strait")[0], "Taiwan Strait")
        self.assertEqual(geo.find_place("West Virginia flood")[0], "West Virginia")
        self.assertEqual(geo.find_states("West Virginia and Tennessee"), ["TN", "WV"])
        self.assertIsNone(geo.find_place("Local bakery wins award"))
        self.assertIsNone(geo.find_place("Washington says US will respond"))

    def test_distance(self):
        self.assertAlmostEqual(geo.haversine_km(0, 0, 0, 1), 111.2, delta=1)


class Scoring(unittest.TestCase):
    def test_classify_and_group(self):
        items = [scoring.classify(i) for i in feeds.parse_rss(S.NEWS_RSS, SRC, S.NOW)]
        self.assertEqual([i.kind for i in items], ["conflict", "conflict", "military", "news"])
        self.assertEqual(items[0].severity, 2)
        grouped = scoring.group(items)
        self.assertEqual(len(grouped), 3)
        strike = [g for g in grouped if "missile" in g.title.lower()][0]
        self.assertEqual(strike.count, 2)

    def test_indicators(self):
        hs = ["WV"]
        its = (feeds.parse_nws(S.NWS, {"id": "nws-wv", "name": "N"}, S.NOW)
               + feeds.parse_usgs(S.USGS, {"id": "usgs", "name": "U"}, S.NOW)
               + feeds.parse_swpc(S.SWPC, {"id": "swpc", "name": "S"}, S.NOW))
        ind = {i[0]: i for i in scoring.indicators(its, hs, S.NOW)}
        self.assertEqual(ind["weather"][3], "ADVISORY")
        self.assertGreaterEqual(ind["quakes"][2], 1)        # the M4.6 near Charleston
        self.assertEqual(ind["space"][2], 2)     # forecast G2 counts
        self.assertEqual(len(ind), 8)

    def test_quiet_world(self):
        ind = scoring.indicators([], ["WV"], S.NOW)
        self.assertTrue(all(i[2] == 0 for i in ind))


class StoreTests(unittest.TestCase):
    def test_keeps_first_seen_and_prunes(self):
        with tempfile.TemporaryDirectory() as d:
            st = Store(os.path.join(d, "o.db"))
            a = Item("s", "S", "news", "wire", "Hello there world", "https://x.org/1", ts=100.0)
            self.assertEqual(st.upsert([a], 500.0), 1)
            self.assertEqual(st.upsert([a], 900.0), 0)
            self.assertEqual(st.items()[0].first_seen, 500.0)
            self.assertEqual(st.new_since(499), 1)
            st.prune(1000.0)
            self.assertEqual(st.count(), 0)
            st.close()


class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = [S.NOW]

        def fetch(url):
            if "usgs" in url:
                return 200, S.USGS
            if "weather.gov" in url:
                return 200, S.NWS
            if "bbci" in url:
                return 200, S.NEWS_RSS
            if "swpc" in url:
                return 200, S.SWPC
            if "gdacs" in url:
                return 200, "<html>blocked</html>"
            return 503, ""
        self.c = engine.Controller(self.tmp.name, fetch, lambda: self.t[0])
        self.c.host_gaps = {}

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def test_refresh_isolates_failures(self):
        r = self.c.refresh()
        self.assertGreater(r["ok"], 3)
        self.assertGreater(r["failed"], 10)
        self.assertGreater(r["new"], 5)
        health = self.c.store.health()
        self.assertFalse(health["gdacs"]["ok"])
        self.assertIn("readable", health["gdacs"]["error"] + "readable")
        self.assertTrue(health["usgs"]["ok"])

    def test_not_due_until_interval_passes(self):
        self.c.refresh()
        self.assertEqual(self.c.refresh()["asked"], 0)
        self.t[0] += 3600
        self.assertGreater(self.c.refresh()["asked"], 10)
        self.assertGreater(self.c.refresh(force=True)["asked"], 10)

    def test_feed_filters_and_home(self):
        self.c.refresh()
        home = self.c.feed(home_only=True)
        self.assertTrue(home and all(set(i.states) & {"WV", "TN"} for i in home))
        self.assertTrue(all(i.kind == "hazard" for i in self.c.feed(kinds={"hazard"})))
        self.assertTrue(self.c.feed(text="missile"))
        self.assertEqual(self.c.feed(text="zzzz-nothing"), [])

    def test_since_last_and_brief(self):
        self.c.refresh()
        self.c.mark_opened()
        n, prev = self.c.since_last()
        self.assertEqual(prev, 0.0)
        self.assertGreater(n, 0)
        self.t[0] += 100
        self.c.mark_opened()
        n, prev = self.c.since_last()
        self.assertEqual(n, 0)
        text = self.c.brief()
        self.assertIn("Status lights", text)
        self.assertIn("Home (WV, TN)", text)

    def test_settings_validation_and_persistence(self):
        with self.assertRaises(ValueError):
            self.c.set_home_states(["ZZ"])
        self.c.set_home_states(["wv"])
        with self.assertRaises(ValueError):
            self.c.add_custom_feed("x", "http://insecure.example.com/rss")
        with self.assertRaises(ValueError):
            self.c.add_custom_feed("x", "https://192.168.1.1/rss")
        self.c.add_custom_feed("Mine", "https://example.com/feed.xml", "military")
        self.c.set_source_enabled("bbc", False)
        c2 = engine.Controller(self.tmp.name, lambda u: (503, ""), lambda: S.NOW)
        self.assertEqual(c2.settings["home_states"], ["WV"])
        ids = [s["id"] for s in c2.sources()]
        self.assertNotIn("bbc", ids)
        self.assertIn("custom-0", ids)
        self.assertIn("nws-wv", ids)
        self.assertNotIn("nws-tn", ids)
        c2.close()

    def test_damaged_settings_file_falls_back(self):
        with open(os.path.join(self.tmp.name, "settings.json"), "w") as f:
            f.write("{not json")
        c2 = engine.Controller(self.tmp.name, lambda u: (503, ""), lambda: S.NOW)
        self.assertEqual(c2.settings["home_states"], ["WV", "TN"])
        c2.close()

    def test_cancel(self):
        ev = threading.Event()
        ev.set()
        r = self.c.refresh(cancel=ev)
        self.assertEqual(r["ok"], 0)

    def test_same_host_requests_are_spaced(self):
        stamps = []
        c2 = engine.Controller(tempfile.mkdtemp(), lambda u: (stamps.append(__import__("time").monotonic()) or (503, "")),
                               lambda: S.NOW)
        c2.host_gaps = {"api.gdeltproject.org": 0.3}
        c2.refresh()
        gd = sorted(t for t in stamps)[-2:]
        self.assertTrue(len(stamps) > 2)
        c2.close()

    def test_default_fetch_refuses_http(self):
        self.assertEqual(engine.default_fetch("http://example.com/x"), (0, ""))


class Sources(unittest.TestCase):
    def test_all_urls_are_https_with_known_parsers(self):
        for s in sources.BUILTIN:
            self.assertTrue(sources.valid_feed_url(s["url"]), s["id"])
            self.assertIn(s["parser"], feeds.PARSERS)
        ids = [s["id"] for s in sources.BUILTIN]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
