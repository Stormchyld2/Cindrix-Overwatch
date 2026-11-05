"""The optional local AI: writes the brief and translates, using the models and engine already kept for Cindrix Ops.

Nothing here talks to the internet. Overwatch starts the same `llama-server` Cindrix Ops uses, on this PC only
(127.0.0.1), with a model file from the Cindrix `models` folder, and stops it when asked or when the app closes.
Everything the model writes is labelled as AI-written and carries the numbered headlines it was built from, so
each claim can be checked against a real source. If anything is missing the plain brief still works.
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from . import scoring

SIZE_TAGS = ("9b", "4b", "2b")


def total_ram_gb():
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32), ("total", ctypes.c_uint64),
                            ("avail", ctypes.c_uint64), ("tp", ctypes.c_uint64), ("ap", ctypes.c_uint64),
                            ("tv", ctypes.c_uint64), ("av", ctypes.c_uint64), ("ae", ctypes.c_uint64)]
            m = MS()
            m.length = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 1024 ** 3
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 ** 2
    except Exception:
        pass
    return 8.0


def size_of(name):
    """'Qwen3.5-4B-Q4_K_M.gguf' -> '4b'. Same rule Cindrix Ops uses, so the same files are found."""
    n = name.lower()
    if not n.endswith(".gguf"):
        return None
    for tag in SIZE_TAGS:
        for m in re.finditer(re.escape(tag), n):
            before = n[m.start() - 1] if m.start() else ""
            after = n[m.end()] if m.end() < len(n) else ""
            if not (before.isdigit() or before == ".") and not after.isalpha():
                return tag
    return None


def is_translation_model(name):
    n = name.lower()
    return n.endswith(".gguf") and bool(re.search(r"(^|[-_.])(hy-?)?mt\d*([-_.]|$)", n)) and size_of(name) is None


def pick_chat_model(files, ram_gb):
    """2B under 12 GB of memory, 4B from 12 GB, as Cindrix Ops does. Falls back to the nearest available size."""
    sized = [(f, size_of(f)) for f in files if size_of(f)]
    if not sized:
        return None
    want = "4b" if ram_gb >= 12 else "2b"
    for f, s in sized:
        if s == want:
            return f
    limit = {"9b": 3, "4b": 2, "2b": 1}[ "9b" if ram_gb >= 16 else "4b" if ram_gb >= 12 else "2b"]
    ok = [(f, s) for f, s in sized if {"9b": 3, "4b": 2, "2b": 1}[s] <= limit]
    return (ok or sized)[-1][0] if ok else sized[0][0]


def locate(root):
    """Looks for the Cindrix program folder: root itself, or a folder inside it called Cindrix."""
    for base in (root, os.path.join(root, "Cindrix")):
        if base and os.path.isdir(os.path.join(base, "models")):
            return base
    return ""


def inventory(root, ram_gb=None):
    """What is available under the chosen folder, in words and paths."""
    base = locate(root) if root else ""
    info = {"base": base, "engine": "", "chat": "", "mt": "", "files": [], "message": ""}
    if not root:
        info["message"] = "No Cindrix folder chosen yet."
        return info
    if not base:
        info["message"] = "That folder has no models folder in it. Pick the Cindrix folder (or the drive that holds it)."
        return info
    eng = os.path.join(base, "engines", "llama-server.exe" if sys.platform == "win32" else "llama-server")
    info["engine"] = eng if os.path.isfile(eng) else ""
    try:
        files = sorted(f for f in os.listdir(os.path.join(base, "models")) if f.lower().endswith(".gguf"))
    except OSError:
        files = []
    info["files"] = files
    info["chat"] = pick_chat_model(files, ram_gb if ram_gb is not None else total_ram_gb()) or ""
    info["mt"] = next((f for f in files if is_translation_model(f)), "")
    if not info["engine"]:
        info["message"] = "The model engine (llama-server) was not found in the engines folder."
    elif not info["chat"]:
        info["message"] = "No Qwen model file (2B, 4B or 9B .gguf) found in the models folder."
    else:
        info["message"] = "Ready to use."
    return info


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AiHost:
    """One llama-server process, bound to this PC only."""

    def __init__(self, engine, model, ctx=4096, threads=None, port=None):
        self.engine, self.model, self.ctx = engine, model, ctx
        self.threads = threads or max(2, min(8, (os.cpu_count() or 4) // 2))
        self.port, self.proc = port or free_port(), None
        self.external = port is not None            # a server somebody else started (used by the tests)

    def start(self):
        if self.external:
            return
        args = [self.engine, "-m", self.model, "--host", "127.0.0.1", "--port", str(self.port), "-c", str(self.ctx),
                "-t", str(self.threads), "--jinja"]
        flags = 0x08000000 if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     cwd=os.path.dirname(self.engine), creationflags=flags)

    def healthy(self):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def wait_ready(self, timeout=300, say=None):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.healthy():
                return
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError("The model engine stopped while loading (is there enough free memory?).")
            if say:
                say(f"Loading the model ({int(time.time() - t0)} s)")
            time.sleep(1.5)
        raise RuntimeError("The model took too long to load.")

    def chat(self, system, user, max_tokens=700, temperature=0.3, extra=None):
        body = {"model": "cindrix", "stream": False, "temperature": temperature, "top_k": 40, "min_p": 0.08,
                "repeat_penalty": 1.05, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False},
                "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]}
        body.update(extra or {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise RuntimeError(f"The model did not answer ({e}).")
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    def stop(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


SYSTEM = (
    "You summarize numbered news headlines for a family that watches world events for early warning. "
    "Use ONLY the headlines you are given. After each point, cite the headline numbers in square brackets, like [3] or [3][7]. "
    "Never add facts, numbers, places or names that are not in the headlines. "
    "Say 'reported' or 'claimed', not 'confirmed'. Items from state media are that government's claims. "
    "Do not predict. Plain words, short sentences. Do not write headings.")

SECTIONS = (
    ("FORCE MOVEMENTS", "deployments, mobilization, readiness and exercises"),
    ("CONFLICT AND CRISES", "fighting, attacks, advisories and unrest"),
    ("HEALTH, WEATHER AND HAZARDS", "outbreaks, storms, quakes and other hazards"),
    ("HOME", "anything touching the home states"),
)


def gather(controller, max_items=36, hours=24):
    """The numbered headlines, sorted by seriousness, and which section each belongs to."""
    items = scoring.group(controller.all_items(hours))
    rank = {"official": 2, "wire": 1, "outlet": 0}
    items.sort(key=lambda i: (-(i.severity), -(1 if scoring.is_deployment(i) else 0), -i.count, -rank[i.trust], -i.ts))
    items = [i for i in items if i.kind in ("military", "conflict", "news", "health", "hazard", "weather", "space")][:max_items]
    hs = controller.settings["home_states"]
    parts = {name: [] for name, _ in SECTIONS}
    for n, it in enumerate(items, 1):
        if scoring.is_home(it, hs):
            parts["HOME"].append(n)
        if scoring.is_deployment(it):
            parts["FORCE MOVEMENTS"].append(n)
        elif it.kind in ("health", "hazard", "weather", "space"):
            parts["HEALTH, WEATHER AND HAZARDS"].append(n)
        elif it.kind in ("conflict", "military", "news"):
            parts["CONFLICT AND CRISES"].append(n)
    return items, parts


def headline_line(n, it):
    tags = [it.kind] + (["force-movement"] if scoring.is_deployment(it) else []) + ([f"{it.count} sources"] if it.count > 1 else [])
    where = f" | {it.place}" if it.place else ""
    return f"[{n}] ({', '.join(tags)}; {it.source}{where}) {it.title}"


def clean_points(text, allowed, limit=5):
    """Keeps the model's bullet points, drops repeats and citations that point outside the section."""
    out, seen = [], set()
    for raw in text.splitlines():
        ln = raw.strip().lstrip("#*-• ").strip()
        if not ln or ln.upper().rstrip(":") in {n for n, _ in SECTIONS} | {"BOTTOM LINE"}:
            continue
        ln = re.sub(r"\[(\d{1,3})\]", lambda m: m.group(0) if int(m.group(1)) in allowed else "", ln)
        ln = re.sub(r"\s{2,}", " ", ln).strip()
        key = re.sub(r"[^a-z0-9]+", " ", ln.lower())
        if not ln or key in seen or len(re.sub(r"\[\d{1,3}\]|[^A-Za-z ]", "", ln).split()) < 3:
            continue                                  # empty, repeated, or just a string of numbers
        seen.add(key)
        out.append("- " + ln)
        if len(out) >= limit:
            break
    return out


DISCLAIMER = ("AI-written summary of the headlines listed under each part, made on this PC by a small model. It can miss things or "
              "word them badly, so the full list of headlines is always shown. Check the sources before relying on anything.")


def short(it, n):
    return f"  [{n}] {it.title} ({it.source}{', ' + it.url if it.url else ''})"


def build_brief(items, parts, summaries, bottom):
    out = [DISCLAIMER, "", "BOTTOM LINE"] + (bottom or ["- (The model gave no summary.)"]) + [""]
    for name, _ in SECTIONS:
        nums = parts[name]
        out.append(name)
        if not nums:
            out += ["- Nothing reported.", ""]
            continue
        out += summaries.get(name) or ["- (The model gave no summary for this part.)"]
        out.append("  Headlines:")
        out += [short(items[n - 1], n) for n in nums[:8]]
        if len(nums) > 8:
            out.append(f"  ...and {len(nums) - 8} more in the feed.")
        out.append("")
    return "\n".join(out).rstrip()


class AiService:
    """Starts the model when needed, writes the brief, stops again. Used by the window and the tests."""

    def __init__(self, controller, host_factory=None):
        self.c = controller
        self.host, self.lock = None, threading.Lock()
        self.host_factory = host_factory
        self.last_error = ""

    def root(self):
        return self.c.settings.get("ai_root", "")

    def status(self):
        info = inventory(self.root())
        info["enabled"] = bool(self.c.settings.get("ai_enabled", False))
        info["running"] = bool(self.host and self.host.healthy())
        return info

    def _ensure(self, say=None):
        with self.lock:
            if self.host and self.host.healthy():
                return self.host
            if self.host_factory:
                self.host = self.host_factory()
            else:
                info = inventory(self.root())
                if info["message"] != "Ready to use.":
                    raise RuntimeError(info["message"])
                ram = total_ram_gb()
                model = os.path.join(info["base"], "models", info["chat"])
                self.host = AiHost(info["engine"], model, ctx=4096 if ram >= 6 else 2048)
            if say:
                say("Starting the model on this PC")
            self.host.start()
            self.host.wait_ready(say=say)
            return self.host

    def write_brief(self, say=None):
        host = self._ensure(say)
        small = "2b" in (getattr(host, "model", "") or "").lower()
        items, parts = gather(self.c, max_items=24 if small else 36)
        if not items:
            raise RuntimeError("There is nothing saved from the last 24 hours yet. Refresh first.")
        home = ", ".join(self.c.settings["home_states"]) or "not set"
        summaries = {}
        todo = [(name, why) for name, why in SECTIONS if parts[name]]
        for k, (name, why) in enumerate(todo, 1):
            if say:
                say(f"Writing part {k} of {len(todo) + 1}: {name.title()}")
            lines = "\n".join(headline_line(n, items[n - 1]) for n in parts[name][:10])
            prompt = (f"Part: {name} ({why}). Home states: {home}.\n\nHeadlines:\n{lines}\n\n"
                      "Write 2 to 4 short bullet points that summarize only these headlines. Start each with '- ' and end each "
                      "with the headline numbers in square brackets.")
            summaries[name] = clean_points(host.chat(SYSTEM, prompt, max_tokens=260, temperature=0.3), set(parts[name]))
        if say:
            say(f"Writing part {len(todo) + 1} of {len(todo) + 1}: Bottom line")
        top = list(range(1, min(len(items), 7) + 1))
        lines = "\n".join(headline_line(n, items[n - 1]) for n in top)
        prompt = (f"Home states: {home}.\n\nThe most serious headlines:\n{lines}\n\nWrite exactly two short sentences on what "
                  "matters most right now. End each sentence with the headline numbers in square brackets.")
        bottom = clean_points(host.chat(SYSTEM, prompt, max_tokens=160, temperature=0.3), set(top), limit=2)
        return build_brief(items, parts, summaries, bottom)

    def translate(self, text, target="English", say=None):
        """Uses the translation model when one is in the models folder (Hy-MT style prompt)."""
        info = inventory(self.root())
        if not info["mt"]:
            raise RuntimeError("No translation model in the models folder yet (a file with MT in its name).")
        mt = AiHost(info["engine"], os.path.join(info["base"], "models", info["mt"]), ctx=4096)
        try:
            mt.start()
            mt.wait_ready(say=say)
            out = mt.chat("", f"Translate the following text into {target}. Output only the translation, with no extra "
                              f"explanation:\n\n{text}", max_tokens=1024, temperature=0.7,
                          extra={"top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05})
        finally:
            mt.stop()
        return out

    def stop(self):
        if self.host:
            self.host.stop()
            self.host = None
