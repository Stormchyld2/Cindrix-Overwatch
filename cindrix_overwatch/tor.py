"""Tor support with the standard library only.

Overwatch talks to Tor through its SOCKS5 port. The hostname is always handed to Tor to resolve (never looked up
on this PC), which is required for .onion addresses and keeps normal lookups off your own DNS.

Three ways to get a Tor connection, tried in this order:
  1. the Tor that is bundled inside Overwatch (tor/tor.exe next to the program), started on demand;
  2. a Tor Browser that is already open (SOCKS port 9150);
  3. a Tor service or Orbot-style proxy on port 9050.

This is a plain Tor client for reading public feeds and pages. It is not Tor Browser and it does not give the
browser-level anonymity protections Tor Browser does.
"""

import gzip
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import zlib
from urllib.parse import urljoin, urlparse

ONION_RE = re.compile(r"^[a-z2-7]{56}\.onion$")


def onion_checksum_ok(host):
    """True when a v3 onion address carries a correct built-in checksum (a mistyped one almost never does)."""
    import base64
    import hashlib
    h = (host or "").lower().replace(".onion", "")
    if not re.fullmatch(r"[a-z2-7]{56}", h):
        return False
    raw = base64.b32decode(h.upper())
    return raw[34] == 3 and hashlib.sha3_256(b".onion checksum" + raw[:32] + b"\x03").digest()[:2] == raw[32:34]
BUNDLED_PORT = 9250
UA = "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
REPLIES = {1: "general failure", 2: "not allowed", 3: "network unreachable", 4: "host unreachable",
           5: "connection refused", 6: "timed out", 7: "command not supported", 8: "address type not supported"}


class TorError(Exception):
    pass


def is_onion_host(host):
    return bool(host) and bool(ONION_RE.match(host.lower()))


def is_onion_url(url):
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and is_onion_host(p.hostname or "")


def _recv(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise TorError("The Tor connection closed unexpectedly.")
        buf += chunk
    return buf


def socks5_connect(host, port, proxy, timeout=30):
    """Opens a connection to host:port through a SOCKS5 proxy, letting the proxy resolve the name."""
    s = socket.create_connection(proxy, timeout=timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        if _recv(s, 2) != b"\x05\x00":
            raise TorError("That port did not answer like a Tor proxy.")
        hb = host.encode("idna")
        if len(hb) > 255:
            raise TorError("Address too long.")
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack(">H", port))
        head = _recv(s, 4)
        if head[1] != 0:
            raise TorError("Tor could not connect: " + REPLIES.get(head[1], f"code {head[1]}"))
        atyp = head[3]
        skip = 4 if atyp == 1 else 16 if atyp == 4 else _recv(s, 1)[0]
        _recv(s, skip + 2)
        return s
    except Exception:
        s.close()
        raise


def probe(port, host="127.0.0.1"):
    """True if something on this port speaks SOCKS5 (a very small handshake, no traffic leaves the PC)."""
    try:
        with socket.create_connection((host, port), timeout=1.5) as s:
            s.settimeout(1.5)
            s.sendall(b"\x05\x01\x00")
            return s.recv(2) == b"\x05\x00"
    except OSError:
        return False


def _dechunk(body):
    out, i = b"", 0
    while True:
        j = body.find(b"\r\n", i)
        if j < 0:
            break
        try:
            n = int(body[i:j].split(b";")[0], 16)
        except ValueError:
            break
        if n == 0:
            break
        out += body[j + 2:j + 2 + n]
        i = j + 2 + n + 2
    return out


def http_get(url, proxy, timeout=45, max_bytes=5_000_000, hops=4):
    """GET through Tor. Returns (status, headers_lowercased, body_bytes). Plain http only for onion addresses."""
    u = urlparse(url)
    host = u.hostname or ""
    if u.scheme not in ("http", "https"):
        raise TorError("Only web addresses can be opened.")
    if u.scheme == "http" and not is_onion_host(host):
        raise TorError("Plain http is only allowed for .onion addresses.")
    https = u.scheme == "https"
    s = socks5_connect(host, u.port or (443 if https else 80), proxy, timeout)
    try:
        if https:
            ctx = ssl.create_default_context()
            if is_onion_host(host):
                # An onion address is the service's own public key, and Tor already proves you reached it, so a web
                # certificate adds nothing (most onion sites use self-signed ones). Normal websites stay fully verified.
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(s, server_hostname=host)
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        req = (f"GET {path} HTTP/1.1\r\nHost: {u.netloc}\r\nUser-Agent: {UA}\r\n"
               "Accept: text/html,application/rss+xml,application/atom+xml,application/xml,*/*;q=0.8\r\n"
               "Accept-Encoding: gzip\r\nConnection: close\r\n\r\n")
        s.sendall(req.encode("ascii", "replace"))
        data = b""
        deadline = time.monotonic() + timeout * 2
        while len(data) < max_bytes + 65536 and time.monotonic() < deadline:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        try:
            s.close()
        except OSError:
            pass
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    try:
        status = int(lines[0].split()[1])
    except (IndexError, ValueError):
        raise TorError("The site did not answer like a web server.")
    hdrs = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        hdrs[k.strip().lower()] = v.strip()
    if "chunked" in hdrs.get("transfer-encoding", "").lower():
        body = _dechunk(body)
    try:
        if hdrs.get("content-encoding", "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        elif hdrs.get("content-encoding", "").lower() == "deflate":
            body = zlib.decompress(body)
    except (OSError, EOFError, zlib.error):
        pass
    if status in (301, 302, 303, 307, 308) and hdrs.get("location") and hops > 0:
        nxt = urljoin(url, hdrs["location"])
        np = urlparse(nxt)
        if np.scheme == "https" or (np.scheme == "http" and is_onion_host(np.hostname or "")):
            return http_get(nxt, proxy, timeout, max_bytes, hops - 1)
        raise TorError("The site tried to send you somewhere insecure.")
    return status, hdrs, body[:max_bytes]


def tor_fetch(url, proxy, timeout=45):
    """Same shape as the normal fetch: (status, text)."""
    try:
        status, _, body = http_get(url, proxy, timeout)
        return status, body.decode("utf-8", "replace")
    except (TorError, OSError, ssl.SSLError, ValueError) as e:
        return 0, str(e)[:120]


class BundledTor:
    """The Tor program shipped inside Overwatch, started only when asked for and stopped when the app closes."""

    def __init__(self, data_root, exe=None):
        self.data_root = data_root
        self.exe = exe or self._default_exe()
        self.state = "off"           # off, starting, ready, failed
        self.progress = ""
        self.proc = None
        self._lock = threading.Lock()

    @staticmethod
    def _default_exe():
        bases = [getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(sys.argv[0] or "."))]
        for b in bases:
            if b:
                p = os.path.join(b, "tor", "tor.exe" if sys.platform == "win32" else "tor")
                if os.path.isfile(p):
                    return p
        return ""

    def available(self):
        return bool(self.exe) and os.path.isfile(self.exe)

    def start(self):
        with self._lock:
            if self.state in ("starting", "ready") or not self.available():
                return self.state
            self.state, self.progress = "starting", "Starting Tor"
        datadir = os.path.join(self.data_root, "tor-data")
        os.makedirs(datadir, exist_ok=True)
        args = [self.exe, "--SocksPort", f"127.0.0.1:{BUNDLED_PORT}", "--DataDirectory", datadir, "--ClientOnly", "1",
                "--Log", "notice stdout"]
        geo = os.path.join(os.path.dirname(self.exe), "..", "data", "geoip")
        if os.path.isfile(geo):
            args += ["--GeoIPFile", os.path.normpath(geo)]
        flags = 0x08000000 if sys.platform == "win32" else 0         # CREATE_NO_WINDOW
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         creationflags=flags, cwd=os.path.dirname(self.exe), env=clean_env())
        except OSError as e:
            self.state, self.progress = "failed", f"Could not start Tor ({e.strerror or e})"
            return self.state
        threading.Thread(target=self._watch, daemon=True).start()
        return self.state

    def _watch(self):
        for line in self.proc.stdout:
            m = re.search(r"Bootstrapped (\d+)%[^:]*: (.*)", line)
            if m:
                self.progress = f"Connecting to Tor: {m.group(1)}% ({m.group(2).strip()[:40]})"
                if m.group(1) == "100":
                    self.state, self.progress = "ready", "Tor is connected"
            elif "[err]" in line:
                self.progress = line.strip()[-100:]
        if self.state != "ready":
            self.state = "failed"
            self.progress = self.progress or "Tor stopped before it connected"
        else:
            self.state, self.progress = "off", "Tor stopped"

    def stop(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.state = "off"

    def proxy(self):
        return ("127.0.0.1", BUNDLED_PORT) if self.state == "ready" else None


class TorLink:
    """Finds whichever Tor connection is usable right now and says in words what it is using."""

    def __init__(self, data_root, bundled=None):
        self.bundled = bundled or BundledTor(data_root)
        self.ports = ((9150, "Tor Browser"), (9050, "a Tor service or Orbot"))

    def proxy(self):
        p = self.bundled.proxy()
        if p:
            return p
        for port, _ in self.ports:
            if probe(port):
                return ("127.0.0.1", port)
        return None

    def describe(self):
        if self.bundled.state == "ready":
            return "Using the Tor built into Overwatch."
        if self.bundled.state == "starting":
            return self.bundled.progress
        for port, name in self.ports:
            if probe(port):
                return f"Using {name} (port {port})."
        if self.bundled.state == "failed":
            return self.bundled.progress
        if self.bundled.available():
            return "Tor is not running. Press Start Tor."
        return "No Tor found. This build has no built-in Tor; open Tor Browser or Orbot, or install a newer Overwatch."

    def fetch(self, url):
        p = self.proxy()
        if not p:
            return 0, "Needs Tor, which is not running"
        return tor_fetch(url, p)

    def close(self):
        self.bundled.stop()


def clean_env():
    """A copy of the environment without what a PyInstaller program adds. Firefox loads its own DLLs, and PATH entries
    pointing into our unpacked temp folder make it fail with 'Couldn't load XPCOM'."""
    env = dict(os.environ)
    mei = getattr(sys, "_MEIPASS", "")
    if mei:
        parts = [p for p in env.get("PATH", "").split(os.pathsep) if p and os.path.normcase(p) != os.path.normcase(mei)
                 and not os.path.normcase(p).startswith(os.path.normcase(mei))]
        env["PATH"] = os.pathsep.join(parts)
    for k in list(env):
        if k.startswith("_PYI") or k in ("_MEIPASS2", "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
            env.pop(k, None)
    return env


def start_browser(exe, url=""):
    """Starts Tor Browser the way its own shortcut does: from its own folder, with a clean environment."""
    try:
        subprocess.Popen([exe] + ([url] if url else []), cwd=os.path.dirname(exe), env=clean_env())
        return True
    except OSError:
        return False


def find_tor_browser(root=""):
    """Path of a Tor Browser install if there is one (the copy Overwatch installed first, then the usual places)."""
    names = []
    if root:
        names += [os.path.join(root, "TorBrowser", "Browser", "firefox.exe"),
                  os.path.join(root, "TorBrowser", "Tor Browser", "Browser", "firefox.exe")]
    if sys.platform == "win32":
        home = os.path.expanduser("~")
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", ""), os.path.join(home, "Desktop"),
                     os.path.join(home, "Downloads"), os.path.join(home, "OneDrive", "Desktop")):
            if base:
                names.append(os.path.join(base, "Tor Browser", "Browser", "firefox.exe"))
    for n in names:
        if os.path.isfile(n):
            return n
    return ""
