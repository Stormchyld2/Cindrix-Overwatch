"""CI helper: downloads the Tor Expert Bundle for Windows (Tor Project, BSD licence) into tor_bundle/.

Checks the download against the SHA-256 list published beside it. If anything fails it exits non-zero and the build
carries on without a built-in Tor (the app then uses Tor Browser or Orbot if they are running).
"""
import hashlib
import io
import re
import sys
import tarfile
import urllib.request

BASE = "https://dist.torproject.org/torbrowser/"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "CindrixOverwatch-build"}), timeout=120) as r:
        return r.read()


def main():
    listing = get(BASE).decode("utf-8", "replace")
    vers = sorted({tuple(int(x) for x in v.split(".")) for v in re.findall(r'href="(\d+\.\d+(?:\.\d+)?)/"', listing)},
                  reverse=True)
    for ver in vers[:4]:
        v = ".".join(map(str, ver))
        name = f"tor-expert-bundle-windows-x86_64-{v}.tar.gz"
        try:
            data = get(f"{BASE}{v}/{name}")
            sums = get(f"{BASE}{v}/sha256sums-signed-build.txt").decode()
        except Exception as e:
            print("skip", v, e)
            continue
        want = re.search(r"([0-9a-f]{64})\s+" + re.escape(name), sums)
        got = hashlib.sha256(data).hexdigest()
        if not want or want.group(1) != got:
            print("checksum mismatch for", name)
            sys.exit(1)
        tarfile.open(fileobj=io.BytesIO(data)).extractall("tor_bundle", filter="data")
        print("Tor Expert Bundle", v, "verified (sha256) and unpacked")
        return
    print("no bundle found")
    sys.exit(1)


main()
