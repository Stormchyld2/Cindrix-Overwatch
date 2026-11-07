# Cindrix Overwatch

A war-room monitor for current events around the world, part of the Cindrix line. Windows app, Python standard library only.

- **World map** with pins for conflict, military items, hazards and news, plus a HOME marker for your states.
- **Feed** that groups the same story from many outlets into one item with a source count, and says who reported it (official, wire, single outlet).
- **Status lights** for home weather, power grid, quakes near home, outbreaks, space weather, conflict reporting, military activity and supply news. They measure how much is being reported, not confirmed facts.
- **Saved history** (30 days, SQLite) so the last picture is still there when the internet is not.
- **AI map pins** (only with the AI switched on): for stories the built-in place list could not pin, the local model names the place and the list supplies the coordinates, so a pin is never invented. Pins are marked "placed by AI".
- **Daily brief**, "since you last looked" counter, your own custom feeds, and a Sources tab showing which feeds work.

Public feeds only: USGS, NWS, NASA EONET, GDACS, NOAA space weather, ReliefWeb, WHO, GDELT, world news RSS, and official military and defense releases. No logins, no keys, no tracking of people. Nothing is sent anywhere except requests to those sources.

## Get the exe

Open the newest **build-windows** run in the Actions tab: the exe is at the top (link) and under Artifacts at the bottom. The same build is on the Releases page as `latest`. Windows may warn about an unknown publisher because the app is not code-signed; choose More info, then Run anyway.

Data is stored in `Downloads/Cindrix/Overwatch`.

## Development

    python -m unittest discover -s tests -t .
    python -m tests.smoke_ui          # opens the real window with fake data (needs a display)
    python -m tests.check_feeds       # hits the real sources and prints what works

World outline: Natural Earth (public domain), added by the `map-data` workflow.
