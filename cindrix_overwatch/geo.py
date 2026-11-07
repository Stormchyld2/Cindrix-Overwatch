"""Small built-in gazetteer: finds a place in a headline so an item can be pinned on the map.

Only places named in the text are matched. The country of the publisher is never used, because an outlet
in one country often reports on another. No match means no pin, which is better than a wrong pin.
"""

import math
import re

# code|name|lat|lon (state centres, rough)
_STATES = """AL|Alabama|32.8|-86.8
AK|Alaska|64.2|-149.5
AZ|Arizona|34.3|-111.7
AR|Arkansas|34.9|-92.4
CA|California|37.2|-119.5
CO|Colorado|39.0|-105.5
CT|Connecticut|41.6|-72.7
DE|Delaware|39.0|-75.5
FL|Florida|28.6|-82.4
GA|Georgia (US)|32.7|-83.4
HI|Hawaii|20.8|-156.3
ID|Idaho|44.4|-114.6
IL|Illinois|40.0|-89.2
IN|Indiana|39.9|-86.3
IA|Iowa|42.1|-93.5
KS|Kansas|38.5|-98.4
KY|Kentucky|37.5|-85.3
LA|Louisiana|31.1|-92.0
ME|Maine|45.4|-69.2
MD|Maryland|39.0|-76.8
MA|Massachusetts|42.3|-71.8
MI|Michigan|44.3|-85.4
MN|Minnesota|46.3|-94.3
MS|Mississippi|32.7|-89.7
MO|Missouri|38.4|-92.5
MT|Montana|47.0|-109.6
NE|Nebraska|41.5|-99.8
NV|Nevada|39.3|-116.6
NH|New Hampshire|43.7|-71.6
NJ|New Jersey|40.1|-74.7
NM|New Mexico|34.4|-106.1
NY|New York|42.9|-75.5
NC|North Carolina|35.6|-79.4
ND|North Dakota|47.5|-100.5
OH|Ohio|40.3|-82.8
OK|Oklahoma|35.6|-97.5
OR|Oregon|43.9|-120.6
PA|Pennsylvania|40.9|-77.8
RI|Rhode Island|41.7|-71.5
SC|South Carolina|33.9|-80.9
SD|South Dakota|44.4|-100.2
TN|Tennessee|35.8|-86.3
TX|Texas|31.5|-99.3
UT|Utah|39.3|-111.7
VT|Vermont|44.0|-72.7
VA|Virginia|37.5|-78.8
WA|Washington State|47.4|-120.5
WV|West Virginia|38.6|-80.6
WI|Wisconsin|44.6|-89.9
WY|Wyoming|43.0|-107.5
DC|District of Columbia|38.9|-77.0
PR|Puerto Rico|18.2|-66.5"""

STATES = {}
for _line in _STATES.splitlines():
    _c, _n, _la, _lo = _line.split("|")
    STATES[_c] = (_n, float(_la), float(_lo))

# name|lat|lon, countries and hot-spot regions that show up in headlines
_PLACES = """Afghanistan|34.0|66.0
Albania|41.1|20.0
Algeria|28.0|2.6
Angola|-12.0|17.5
Argentina|-34.0|-64.0
Armenia|40.2|45.0
Australia|-25.0|134.0
Azerbaijan|40.3|47.7
Bangladesh|23.8|90.3
Belarus|53.7|27.9
Belgium|50.6|4.7
Bolivia|-16.7|-64.7
Bosnia|44.0|17.8
Brazil|-10.0|-52.0
Bulgaria|42.7|25.2
Burkina Faso|12.3|-1.6
Cambodia|12.6|104.9
Cameroon|5.7|12.7
Canada|56.0|-96.0
Chad|15.4|18.7
Chile|-33.0|-71.0
China|35.0|103.0
Colombia|4.6|-74.1
Congo|-2.9|23.7
Cuba|21.6|-79.0
Cyprus|35.1|33.2
Czech|49.8|15.5
Denmark|56.0|10.0
Ecuador|-1.4|-78.4
Egypt|26.5|30.0
Estonia|58.7|25.5
Ethiopia|9.1|40.5
Finland|64.0|26.0
France|46.6|2.5
Germany|51.0|10.4
Ghana|7.9|-1.0
Greece|39.1|22.0
Greenland|72.0|-40.0
Guatemala|15.5|-90.3
Haiti|19.0|-72.4
Honduras|14.8|-86.6
Hungary|47.2|19.5
Iceland|65.0|-18.0
India|22.0|79.0
Indonesia|-2.0|118.0
Iran|32.4|53.7
Iraq|33.0|44.0
Ireland|53.3|-8.0
Israel|31.4|35.0
Gaza|31.4|34.4
West Bank|32.0|35.3
Italy|42.8|12.8
Japan|36.5|138.0
Jordan|31.2|36.5
Kazakhstan|48.0|67.0
Kenya|0.2|37.9
Kosovo|42.6|20.9
Kuwait|29.3|47.6
Latvia|56.9|24.9
Lebanon|33.9|35.9
Libya|27.0|17.0
Lithuania|55.3|23.9
Malaysia|3.8|102.0
Mali|17.5|-4.0
Mexico|23.0|-102.0
Moldova|47.2|28.5
Mongolia|46.8|103.0
Morocco|31.8|-6.3
Mozambique|-18.7|35.5
Myanmar|21.0|96.0
Nepal|28.3|84.0
Netherlands|52.2|5.6
Niger|17.6|8.1
Nigeria|9.1|8.7
North Korea|40.3|127.2
Norway|62.0|10.0
Oman|21.5|56.0
Pakistan|30.0|70.0
Panama|8.5|-80.0
Peru|-9.2|-75.0
Philippines|12.8|122.0
Poland|52.0|19.4
Portugal|39.5|-8.0
Qatar|25.3|51.2
Romania|45.9|25.0
Russia|61.5|99.0
Saudi Arabia|24.0|45.0
Serbia|44.0|21.0
Slovakia|48.7|19.5
Somalia|5.2|46.2
South Africa|-29.0|24.0
South Korea|36.5|127.9
South Sudan|7.9|30.0
Spain|40.0|-3.7
Sudan|15.5|30.0
Sweden|62.0|15.0
Switzerland|46.8|8.2
Syria|35.0|38.5
Taiwan|23.7|121.0
Thailand|15.0|101.0
Tunisia|34.0|9.0
Turkey|39.0|35.0
Uganda|1.4|32.3
Ukraine|49.0|32.0
United Arab Emirates|24.0|54.0
United Kingdom|54.0|-2.5
Britain|54.0|-2.5
Uzbekistan|41.4|64.6
Venezuela|7.0|-66.0
Vietnam|16.0|107.0
Yemen|15.6|48.0
Zimbabwe|-19.0|29.8
Black Sea|43.5|34.0
Red Sea|20.0|38.5
Baltic Sea|58.0|20.0
Strait of Hormuz|26.5|56.3
Persian Gulf|27.0|51.5
Gulf of Aden|12.5|47.0
South China Sea|14.0|114.0
East China Sea|29.0|125.0
Taiwan Strait|24.0|119.5
Korean Peninsula|38.0|127.5
Sea of Japan|40.0|134.0
Mediterranean|35.0|18.0
Arctic|80.0|0.0
Sahel|15.0|2.0
Kyiv|50.45|30.52
Moscow|55.75|37.6
Tehran|35.7|51.4
Jerusalem|31.77|35.2
Beijing|39.9|116.4
Pyongyang|39.0|125.75
Damascus|33.5|36.3
Baghdad|33.3|44.4
Kabul|34.5|69.2
Taipei|25.0|121.5
Tokyo|35.7|139.7
Pacific|10.0|-160.0
Atlantic|30.0|-40.0
Caribbean|15.0|-72.0
Antarctica|-80.0|0.0
Kharkiv|49.99|36.23
Odesa|46.48|30.72
Dnipro|48.46|35.05
Zaporizhzhia|47.84|35.14
Kherson|46.64|32.62
Mariupol|47.10|37.54
Donetsk|48.0|37.8
Luhansk|48.57|39.31
Lviv|49.84|24.03
Sevastopol|44.62|33.52
Bakhmut|48.59|38.0
Pokrovsk|48.28|37.18
Sumy|50.91|34.80
Donbas|48.3|38.0
Crimea|45.3|34.4
St. Petersburg|59.93|30.34
Kaliningrad|54.71|20.51
Minsk|53.90|27.57
Vilnius|54.69|25.28
Riga|56.95|24.11
Tallinn|59.44|24.75
Novorossiysk|44.72|37.77
Belgorod|50.60|36.59
Kursk|51.73|36.19
Vladivostok|43.12|131.89
Murmansk|68.97|33.09
Isfahan|32.65|51.67
Bandar Abbas|27.18|56.27
Natanz|33.72|51.73
Tel Aviv|32.09|34.78
Haifa|32.79|34.99
Gaza City|31.50|34.47
Rafah|31.30|34.25
Khan Younis|31.35|34.31
Golan Heights|33.0|35.8
Beirut|33.89|35.50
Aleppo|36.20|37.16
Idlib|35.93|36.63
Homs|34.73|36.72
Mosul|36.34|43.13
Erbil|36.19|44.01
Basra|30.51|47.78
Amman|31.95|35.93
Riyadh|24.71|46.68
Jeddah|21.54|39.17
Sanaa|15.37|44.19
Aden|12.78|45.04
Hodeidah|14.80|42.95
Muscat|23.59|58.41
Doha|25.29|51.53
Dubai|25.20|55.27
Abu Dhabi|24.45|54.38
Kuwait City|29.38|47.99
Manama|26.23|50.59
Ankara|39.93|32.86
Istanbul|41.01|28.98
Suez Canal|30.5|32.3
Bab el-Mandeb|12.6|43.3
Sinai|29.5|33.8
Seoul|37.57|126.98
Busan|35.18|129.08
Osaka|34.69|135.50
Okinawa|26.50|128.0
Shanghai|31.23|121.47
Hong Kong|22.32|114.17
Shenzhen|22.54|114.06
Guangzhou|23.13|113.26
Chengdu|30.57|104.07
Kaohsiung|22.63|120.30
Kinmen|24.45|118.38
Strait of Malacca|2.5|101.5
Guam|13.44|144.79
Manila|14.60|120.98
Hanoi|21.03|105.85
Ho Chi Minh City|10.82|106.63
Bangkok|13.76|100.50
Jakarta|-6.21|106.85
Singapore|1.35|103.82
Kuala Lumpur|3.14|101.69
Naypyidaw|19.76|96.08
Yangon|16.84|96.17
Dhaka|23.81|90.41
New Delhi|28.61|77.21
Mumbai|19.08|72.88
Kolkata|22.57|88.36
Srinagar|34.08|74.80
Islamabad|33.68|73.05
Karachi|24.86|67.01
Lahore|31.55|74.34
Kandahar|31.63|65.71
Kathmandu|27.72|85.32
Colombo|6.93|79.86
Ulaanbaatar|47.92|106.92
Astana|51.17|71.43
Almaty|43.24|76.89
Tashkent|41.30|69.24
Cairo|30.04|31.24
Alexandria|31.20|29.92
Khartoum|15.50|32.56
Omdurman|15.64|32.48
El Fasher|13.63|25.35
Port Sudan|19.62|37.22
Juba|4.85|31.58
Addis Ababa|9.03|38.74
Mogadishu|2.05|45.32
Nairobi|-1.29|36.82
Kampala|0.35|32.58
Kigali|-1.95|30.06
Goma|-1.68|29.22
Kinshasa|-4.44|15.27
Lagos|6.52|3.38
Abuja|9.06|7.49
Niamey|13.51|2.11
Ouagadougou|12.37|-1.52
Bamako|12.64|-8.00
Dakar|14.72|-17.47
Tripoli|32.89|13.19
Benghazi|32.12|20.07
Tunis|36.81|10.18
Algiers|36.75|3.06
Rabat|34.02|-6.84
Johannesburg|-26.20|28.05
Cape Town|-33.92|18.42
Maputo|-25.97|32.57
Luanda|-8.84|13.23
Harare|-17.83|31.05
Accra|5.60|-0.19
Abidjan|5.36|-4.01
Svalbard|78.2|15.6
London|51.51|-0.13
Paris|48.86|2.35
Berlin|52.52|13.40
Brussels|50.85|4.35
Amsterdam|52.37|4.90
Madrid|40.42|-3.70
Rome|41.90|12.50
Warsaw|52.23|21.01
Rzeszow|50.04|22.00
Gdansk|54.35|18.65
Bucharest|44.43|26.10
Constanta|44.18|28.65
Belgrade|44.79|20.45
Budapest|47.50|19.04
Prague|50.08|14.44
Vienna|48.21|16.37
Athens|37.98|23.73
Helsinki|60.17|24.94
Stockholm|59.33|18.07
Oslo|59.91|10.75
Copenhagen|55.68|12.57
Lisbon|38.72|-9.14
Dublin|53.35|-6.26
Chisinau|47.01|28.86
Tiraspol|46.84|29.63
Pristina|42.66|21.17
Sarajevo|43.86|18.41
Tbilisi|41.72|44.79
Yerevan|40.18|44.51
Baku|40.41|49.87
Washington DC|38.90|-77.04
New York City|40.71|-74.01
Los Angeles|34.05|-118.24
Mexico City|19.43|-99.13
Havana|23.11|-82.37
Port-au-Prince|18.59|-72.31
Caracas|10.48|-66.90
Bogota|4.71|-74.07
Panama City|8.98|-79.52
Brasilia|-15.79|-47.88
Sao Paulo|-23.55|-46.63
Buenos Aires|-34.60|-58.38
Lima|-12.05|-77.04
Santiago|-33.45|-70.67
Ottawa|45.42|-75.70
Toronto|43.65|-79.38
Guantanamo|19.9|-75.15
Essequibo|5.5|-59.0
Canberra|-35.28|149.13
Sydney|-33.87|151.21
Darwin|-12.46|130.84
Auckland|-36.85|174.76
Port Moresby|-9.44|147.18"""

PLACES = []
for _line in _PLACES.splitlines():
    _n, _la, _lo = _line.split("|")
    PLACES.append((_n, float(_la), float(_lo)))

_PLACE_RES = [(re.compile(r"\b" + re.escape(n.split(" (")[0]) + r"\b", re.I if len(n) > 4 else 0), n, la, lo)
              for n, la, lo in PLACES]
_STATE_RES = [(re.compile(r"\b" + re.escape(n.split(" (")[0]) + r"\b"), c, n, la, lo)
              for c, (n, la, lo) in STATES.items() if n not in ("Washington State", "Georgia (US)")]
_STATE_RES.append((re.compile(r"\b(WV|W\.Va\.)\b"), "WV", "West Virginia", 38.6, -80.6))


def _scan_states(text):
    """US states named in text. Longest names go first and are blanked out, so 'West Virginia' is not also 'Virginia'."""
    work, found = text or "", []
    for rx, code, name, la, lo in sorted(_STATE_RES, key=lambda r: -len(r[2])):
        if rx.search(work):
            found.append((code, name, la, lo))
            work = rx.sub(" ", work)
    return found


def find_place(text):
    """Returns (name, lat, lon) for the longest place named in text, or None."""
    best = None
    for rx, name, la, lo in _PLACE_RES:
        m = rx.search(text or "")
        if m and (best is None or len(m.group(0)) > best[3]):
            best = (name.split(" (")[0], la, lo, len(m.group(0)))
    if best:
        return best[:3]
    found = _scan_states(text)
    if found:
        c, n, la, lo = found[0]
        return (n, la, lo)
    return None


def find_states(text):
    """Two-letter codes of US states named in the text."""
    return sorted(c for c, *_ in _scan_states(text))


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def home_point(states):
    """Average centre of the home states, or None."""
    pts = [STATES[s][1:] for s in states if s in STATES]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


# Rough world regions for the Intel filters. Based on where a story is pinned, so a story that is not on the map has no region.
REGIONS = ("Americas", "Europe", "Middle East", "Africa", "Asia-Pacific")


def region_of(lat, lon):
    if -170 <= lon <= -30:
        return "Americas"
    if 12 <= lat <= 42 and 34 <= lon <= 63:
        return "Middle East"
    if lat >= 35 and -25 <= lon <= 45:
        return "Europe"
    if -35 <= lat < 35 and -20 <= lon <= 55:
        return "Africa"
    return "Asia-Pacific"
