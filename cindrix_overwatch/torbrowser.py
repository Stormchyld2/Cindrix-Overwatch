"""Installs the real Tor Browser into the Overwatch folder, checked against the Tor Project's published checksum.

Overwatch does not try to be a browser. Tor Browser is the only browser built to hide you on Tor, so Overwatch fetches
it from the Tor Project, verifies it, installs it quietly into its own folder and opens it for you.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

BASE = "https://dist.torproject.org/torbrowser/"


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "CindrixOverwatch"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def install_dir(root):
    return os.path.join(root, "TorBrowser")


def firefox_path(root):
    for rel in (("Browser", "firefox.exe"), ("Tor Browser", "Browser", "firefox.exe")):
        p = os.path.join(install_dir(root), *rel)
        if os.path.isfile(p):
            return p
    return ""


def _dir_size(path):
    total = 0
    for base, _, files in os.walk(path):
        for n in files:
            try:
                total += os.path.getsize(os.path.join(base, n))
            except OSError:
                pass
    return total


def problem(root):
    """'' when the install looks complete, else a plain sentence saying what is wrong with it."""
    ff = firefox_path(root)
    if not ff:
        return "Tor Browser is not installed."
    xul = os.path.join(os.path.dirname(ff), "xul.dll")
    if sys.platform == "win32" and (not os.path.isfile(xul) or os.path.getsize(xul) < 20_000_000):
        return ("The Tor Browser files on this PC are damaged or incomplete (an install was cut short, or a virus "
                "checker changed a file). Press Install Tor Browser again to put a fresh copy in.")
    return ""


def pick_installer(sums_text):
    """(filename, sha256) of the Windows 64-bit installer named in the Tor Project's checksum list, or None."""
    for pat in (r"torbrowser-install-win64-[\d.]+_ALL\.exe", r"torbrowser-install-win64-[\d.]+_en-US\.exe",
                r"tor-browser-windows-x86_64-portable-[\d.]+\.exe"):
        m = re.search(r"([0-9a-f]{64})\s+\*?(" + pat + ")", sums_text)
        if m:
            return m.group(2), m.group(1)
    return None


def latest(get=_get):
    """Finds the newest version whose checksum list names a Windows installer. Returns (version, name, sha256)."""
    listing = get(BASE).decode("utf-8", "replace")
    vers = sorted({tuple(int(x) for x in v.split(".")) for v in re.findall(r'href="(\d+\.\d+(?:\.\d+)?)/"', listing)},
                  reverse=True)
    for ver in vers[:5]:
        v = ".".join(map(str, ver))
        try:
            sums = get(f"{BASE}{v}/sha256sums-signed-build.txt").decode()
        except Exception:
            continue
        pick = pick_installer(sums)
        if pick:
            return v, pick[0], pick[1]
    raise RuntimeError("Could not find a Tor Browser download on the Tor Project site.")


def install(root, say=None, get=_get, run=subprocess.run):
    """Downloads, verifies and installs. Returns the path to firefox.exe. Raises RuntimeError with a plain message."""
    say = say or (lambda m: None)
    if sys.platform != "win32" and get is _get:
        raise RuntimeError("The one-click install is for Windows.")
    say("Asking the Tor Project for the newest version")
    v, name, want = latest(get)
    say(f"Downloading Tor Browser {v} (about 100 MB)")
    data = get(f"{BASE}{v}/{name}", timeout=900)
    say("Checking the download against the Tor Project checksum")
    if hashlib.sha256(data).hexdigest() != want:
        raise RuntimeError("The download did not match the Tor Project checksum, so it was thrown away.")
    dest = install_dir(root)
    if os.path.isdir(dest):                        # a half-written earlier install is removed first
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    exe = os.path.join(root, name)
    with open(exe, "wb") as f:
        f.write(data)
    say("Installing quietly into the Overwatch folder (this takes a minute or two; do not close Overwatch)")
    cmd = [exe, "/S", "/D=" + dest]            # tested on a Windows runner: unpacks to <dest>\\Browser\\firefox.exe
    proc = subprocess.Popen(cmd) if run is subprocess.run else None
    if proc is None:
        run(cmd)
    # Wait for the installer to finish by itself. Killing it early leaves files half written (a broken xul.dll).
    # Only if it lingers after the files stopped growing for a while is it ended.
    deadline = time.monotonic() + 600
    last, still = -1, 0
    while time.monotonic() < deadline:
        if proc is None or proc.poll() is not None:
            break
        size = _dir_size(dest)
        still = still + 2 if size == last and firefox_path(root) else 0
        last = size
        if still >= 30:
            break
        time.sleep(2)
    if proc is not None and proc.poll() is None:
        proc.terminate()
    time.sleep(2)
    try:
        os.remove(exe)
    except OSError:
        pass
    p = firefox_path(root)
    bad = problem(root) if p else ""
    if bad:
        raise RuntimeError(bad + " If it happens again, add the Overwatch folder to your virus checker's exclusions.")
    if not p:
        seen = []
        for base, dirs, files in os.walk(root):
            seen += [os.path.join(base, n)[len(root):] for n in dirs + files]
            if len(seen) > 25:
                break
        rc = proc.poll() if proc is not None else "n/a"
        raise RuntimeError(f"The installer ran (exit {rc}) but Tor Browser was not found afterwards. Seen: {seen[:25]}")
    say(f"Tor Browser {v} is ready")
    return p


def launch(root, url=""):
    p = firefox_path(root)
    if not p or problem(root):
        return False
    from . import tor
    return tor.start_browser(p, url)
