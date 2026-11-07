"""Phone link: lets the Overwatch phone app watch these cameras from away from home.

The phone and this PC both join the same CindrixVPN server, so they can reach each other. This module is the PC's end:
  * a small relay for each camera, passing the camera's video through unchanged (the camera itself is never opened to the internet);
  * a tiny sync page that hands the camera list to a phone that knows the pairing code.
Nothing here talks to the internet. It listens only when the person has switched it on, and a new code cuts off old phones."""

import hmac
import http.server
import json
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

SYNC_PORT = 8099
RELAY_BASE = 8600
VPN_PREFIX = "10.66.66."
CODE_VERSION = "OW1"


def new_token():
    """16 letters and digits (80 bits), easy to read out and copy."""
    import base64
    return base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=")


def _source_ip(target):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def lan_ip():
    ip = _source_ip("192.0.2.1")
    return None if ip in (None, "0.0.0.0") or ip.startswith("127.") else ip


def vpn_ip(prefix=VPN_PREFIX):
    """This PC's address on the VPN, if it is connected (the address starts with the VPN's network)."""
    ip = _source_ip(prefix + "1")
    return ip if ip and ip.startswith(prefix) else None


def make_code(lan, vpn, port, token):
    return "/".join([CODE_VERSION, lan or "-", vpn or "-", str(port), token])


def parse_code(code):
    """(lan, vpn, port, token) from a pairing code, or None when it is not one."""
    parts = (code or "").strip().split("/")
    if len(parts) != 5 or parts[0] != CODE_VERSION:
        return None
    _v, lan, vpn, port, token = parts
    if not port.isdigit() or not (1 <= int(port) <= 65535) or not token.isalnum():
        return None
    return (None if lan == "-" else lan, None if vpn == "-" else vpn, int(port), token)


def camera_entry(cam, relay_port):
    """What the phone is told about one camera. It builds the address itself from the host it reached this PC on."""
    from . import cameras
    from urllib.parse import urlsplit as _u
    entry = {"id": cam["id"], "name": cam["name"], "brand": cam.get("brand", "other"), "port": relay_port,
             "user": cam.get("user", ""), "password": cam.get("password", "")}
    for key, field in (("main", "main"), ("sub", "sub")):
        u = _u(cam.get(field) or "")
        entry[key] = {"scheme": u.scheme, "path": (u.path or "/") + (("?" + u.query) if u.query else "")} if u.scheme else None
    entry["target"] = cameras.host_label(cam)
    return entry


class Relay(threading.Thread):
    """Passes one TCP port through to a camera. Each phone connection gets its own connection to the camera."""

    def __init__(self, listen_port, target_fn, bind="0.0.0.0"):
        super().__init__(daemon=True)
        self.target_fn = target_fn
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind, listen_port))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.alive = True

    def run(self):
        while self.alive:
            try:
                client, _addr = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._pipe, args=(client,), daemon=True).start()

    def _pipe(self, client):
        try:
            host, port = self.target_fn()
            up = socket.create_connection((host, port), timeout=5)
            up.settimeout(None)
        except (OSError, TypeError, ValueError):
            client.close()
            return

        def pump(a, b):
            try:
                while True:
                    data = a.recv(65536)
                    if not data:
                        break
                    b.sendall(data)
            except OSError:
                pass
            finally:
                for s in (a, b):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    s.close()
        threading.Thread(target=pump, args=(client, up), daemon=True).start()
        threading.Thread(target=pump, args=(up, client), daemon=True).start()

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass


class LinkServer:
    """The relays plus the sync page. `cameras_fn()` returns the enabled cameras, `ports_fn(id)` gives each one its relay port."""

    FAIL_LIMIT = 8
    FAIL_WINDOW = 60.0

    def __init__(self, cameras_fn, ports_fn, token, sync_port=SYNC_PORT, bind="0.0.0.0"):
        self.cameras_fn, self.ports_fn, self.token = cameras_fn, ports_fn, token
        self.bind = bind
        self.relays = {}
        self.fails = []
        self.lock = threading.Lock()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlsplit(self.path)
                if u.path == "/v1/hello":
                    return self._send(200, {"overwatch": 1})
                if u.path != "/v1/cameras":
                    return self._send(404, {"error": "not found"})
                if outer.locked_out():
                    return self._send(429, {"error": "too many tries"})
                given = (parse_qs(u.query).get("token") or [""])[0]
                if not hmac.compare_digest(given.encode(), outer.token.encode()):
                    outer.note_fail()
                    return self._send(403, {"error": "wrong code"})
                self._send(200, {"v": 1, "cameras": outer.camera_list()})

        self.httpd = http.server.ThreadingHTTPServer((bind, sync_port), Handler)
        self.sync_port = self.httpd.server_address[1]

    def locked_out(self):
        now = time.monotonic()
        with self.lock:
            self.fails = [t for t in self.fails if now - t < self.FAIL_WINDOW]
            return len(self.fails) >= self.FAIL_LIMIT

    def note_fail(self):
        with self.lock:
            self.fails.append(time.monotonic())

    def camera_list(self):
        from . import cameras
        out = []
        for cam in self.cameras_fn():
            port = self.ports_fn(cam["id"])
            out.append(camera_entry(cam, port))
        return out

    def sync_relays(self):
        """Opens a relay for each enabled camera and closes the ones no longer wanted."""
        from . import camview
        cams = {c["id"]: c for c in self.cameras_fn()}
        for cid in list(self.relays):
            if cid not in cams:
                self.relays.pop(cid).close()
        for cid, cam in cams.items():
            if cid in self.relays:
                continue
            try:
                r = Relay(self.ports_fn(cid), lambda cid=cid: camview.host_port(next((c["main"] for c in self.cameras_fn() if c["id"] == cid), "")),
                          self.bind)
            except OSError:
                continue
            r.start()
            self.relays[cid] = r

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.sync_relays()

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except OSError:
            pass
        for r in self.relays.values():
            r.close()
        self.relays = {}


def assign_port(ports, cam_id, base=RELAY_BASE):
    """A steady relay port for each camera (the same camera keeps its port, so phones stay paired)."""
    if cam_id in ports:
        return ports[cam_id]
    used = set(ports.values())
    p = base
    while p in used or p == SYNC_PORT:
        p += 1
    ports[cam_id] = p
    return p
