"""IP cameras: the list of supported makes, building a stream address from what the person types, and checking it.

Cameras are reached by their network video address (RTSP is the common one; http web video also works). Nothing here talks to a
camera: it only builds and checks addresses, so it is fully testable."""

import json
import os
import re
import uuid
from urllib.parse import quote, unquote, urlsplit

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCHEMES = ("rtsp", "rtsps", "http", "https")


def catalog():
    with open(os.path.join(DATA, "camera_catalog.json"), encoding="utf-8") as f:
        return json.load(f)


def brands():
    return catalog()["brands"]


def brand(brand_id):
    return next((b for b in brands() if b["id"] == brand_id), None)


def _split_auth(url):
    """Pulls user:password out of an address that has them, so they are stored apart and never shown in the address."""
    p = urlsplit(url)
    if p.username is None:
        return url, "", ""
    host = p.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{p.port}" if p.port else "")
    clean = p._replace(netloc=netloc).geturl()
    return clean, unquote(p.username or ""), unquote(p.password or "")


def valid_address(url):
    try:
        p = urlsplit(url.strip())
        return p.scheme in SCHEMES and bool(p.hostname) and " " not in url.strip()
    except ValueError:
        return False


def build_address(brand_id, host, port=None, stream="main", path_override=""):
    """The address without a password. `host` can be an IP, a name, or a whole address (rtsp://... or http://...).
    A whole address is used as typed. Otherwise the make's usual path and port fill in the rest."""
    host = (host or "").strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", host, re.I):
        return _split_auth(host)[0]
    b = brand(brand_id) or {}
    path = path_override or (b.get("main") if stream == "main" else b.get("sub")) or ""
    if not path:
        return ""
    port = int(port) if port else int(b.get("port") or 554)
    scheme = b.get("scheme") or "rtsp"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{scheme}://{host}:{port}{path if path.startswith('/') else '/' + path}"


def new_camera(name, brand_id, host, user="", password="", port=None, sub_host=""):
    """Makes a camera record, or raises ValueError with a plain-words problem."""
    name = (name or "").strip()[:60] or "Camera"
    host = (host or "").strip()
    if not host:
        raise ValueError("Type the camera's address. It is on the camera's label, in its app, or in your router's list of devices.")
    user_in, pass_in = user or "", password or ""
    if re.match(r"^[a-z][a-z0-9+.-]*://", host, re.I):
        host, u, pw = _split_auth(host)
        user_in, pass_in = user_in or u, pass_in or pw
    if port not in (None, "") and not (str(port).isdigit() and 1 <= int(port) <= 65535):
        raise ValueError("The port must be a number from 1 to 65535.")
    main = build_address(brand_id, host, port, "main")
    if not main:
        raise ValueError("This make has no standard address. Paste the camera's whole address (it starts with rtsp:// or http://).")
    if not valid_address(main):
        raise ValueError("That is not a usable camera address. It should look like 192.168.1.50 or rtsp://192.168.1.50:554/stream1.")
    sub = ""
    if sub_host:
        sub = build_address(brand_id, sub_host, port, "sub")
        if sub and not valid_address(sub):
            raise ValueError("The sub-stream address is not usable.")
    elif not re.match(r"^[a-z][a-z0-9+.-]*://", host, re.I):
        sub = build_address(brand_id, host, port, "sub")
    return {"id": uuid.uuid4().hex[:8], "name": name, "brand": brand_id or "other", "main": main, "sub": sub,
            "user": user_in.strip(), "password": pass_in, "enabled": True}


def stream_address(cam, sub=False):
    """The address to play, with the login put back in. Falls back to the main stream when there is no sub-stream."""
    url = (cam.get("sub") if sub else "") or cam.get("main", "")
    user, pw = cam.get("user", ""), cam.get("password", "")
    if not (user or pw):
        return url
    p = urlsplit(url)
    host = p.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{quote(user, safe='')}:{quote(pw, safe='')}@{host}" + (f":{p.port}" if p.port else "")
    return p._replace(netloc=netloc).geturl()


def shown_address(cam):
    """The address for the screen: never includes the password."""
    return cam.get("main", "")


def host_label(cam):
    """Just the address part (no path, no login) for the small line under a camera's name."""
    try:
        p = urlsplit(cam.get("main", ""))
        return (p.hostname or "") + (f":{p.port}" if p.port else "")
    except ValueError:
        return ""
