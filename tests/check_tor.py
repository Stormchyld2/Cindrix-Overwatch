"""CI only: asks each outlet's own website for its Onion-Location, then reads one feed through a real Tor."""
import sys
import tempfile

from cindrix_overwatch import discover, engine, sources, tor


def main():
    c = engine.Controller(tempfile.mkdtemp())
    found = {}
    for name, home, _ in sources.ONION_OUTLETS:
        loc = c.onion_location(home)
        print(f"{name:36} {loc or '(no Onion-Location header)'}")
        if loc:
            found[name] = loc
    print("proxy:", c.tor.proxy(), "|", c.tor.describe())
    if not c.tor.proxy():
        print("Tor not reachable on this runner")
        sys.exit(1)
    status, text = tor.tor_fetch("https://check.torproject.org/api/ip", c.tor.proxy())
    print("check.torproject.org ->", status, text[:80])
    ok = 0
    for name, loc in list(found.items())[:4]:
        try:
            feeds = discover.find_feeds(c.fetch, loc, print)
            print("FEED over onion:", name, feeds[0]["url"], feeds[0]["count"])
            ok += 1
        except ValueError as e:
            print("no feed over onion:", name, e)
    sys.exit(0 if status == 200 else 1)


main()
