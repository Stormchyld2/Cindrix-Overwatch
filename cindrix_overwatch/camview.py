"""Watchtower playback and recording. A bundled ffmpeg pulls each camera's video: the picture comes back as small PPM frames the
window can show without extra libraries, and recordings are copied straight to disk with no re-encoding.

Everything that can be checked without a screen lives here (building commands, reading frames, retrying, file names, clean-up)."""

import datetime
import os
import re
import shutil
import subprocess
import sys
import threading
import time

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SEGMENT_SECONDS = 900
LOW_DISK_BYTES = 2 * 1024 ** 3


def find_ffmpeg():
    """The ffmpeg that ships inside the program, then one next to it, then one on the PATH. None when there is none."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(sys.argv[0] or ".")), os.path.dirname(os.path.abspath(__file__))):
        p = os.path.join(base, exe) if base else ""
        if p and os.path.isfile(p):
            return p
    return shutil.which("ffmpeg")


def _input_args(url):
    low = url.lower()
    if low.startswith(("rtsp://", "rtsps://")):
        return ["-rtsp_transport", "tcp", "-timeout", "6000000", "-i", url]
    if low.startswith(("http://", "https://")):
        return ["-rw_timeout", "6000000", "-i", url]
    return ["-i", url]


def view_command(ffmpeg, url, width, fps):
    """ffmpeg arguments that print scaled PPM pictures to standard output."""
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *_input_args(url), "-an", "-sn",
            "-vf", f"fps={int(fps)},scale={int(width)}:-2", "-f", "image2pipe", "-vcodec", "ppm", "-"]


def read_ppm(stream):
    """Reads one P6 picture from a binary stream. Returns the whole picture as bytes, or None at the end of the stream."""
    magic = stream.readline()
    if not magic:
        return None
    if magic.strip() != b"P6":
        raise ValueError("not a picture")
    dims = stream.readline()
    while dims.startswith(b"#"):
        dims = stream.readline()
    w, h = (int(x) for x in dims.split())
    maxv = stream.readline()
    if maxv.strip() != b"255":
        raise ValueError("unsupported picture")
    body = _read_exact(stream, w * h * 3)
    if body is None:
        return None
    return magic + dims + maxv + body


def ppm_size(frame):
    parts = frame.split(b"\n", 2)[1].split()
    return int(parts[0]), int(parts[1])


def _read_exact(stream, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


class Feed:
    """One camera's live picture. `frame` is the newest picture, `seq` goes up with every picture, and `state` is
    'connecting', 'live' or 'offline'. A camera that stops sending is shown as offline and tried again on its own."""

    def __init__(self, address_fn, width=640, fps=8, ffmpeg=None, retry=True, stall_seconds=8.0, first_seconds=12.0):
        self.address_fn = address_fn
        self.width, self.fps = width, fps
        self.ffmpeg = ffmpeg or find_ffmpeg()
        self.retry, self.stall, self.first = retry, stall_seconds, first_seconds
        self.state, self.frame, self.seq, self.error = "connecting", None, 0, ""
        self._proc = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._reconfig = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._kill()

    def reconfigure(self, address_fn=None, width=None, fps=None):
        """Switch to another stream or size (for example from the small grid stream to the full one) without waiting."""
        with self._lock:
            if address_fn:
                self.address_fn = address_fn
            if width:
                self.width = width
            if fps:
                self.fps = fps
            self._reconfig = True
        self._kill()

    def _kill(self):
        p = self._proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    def _run(self):
        delay = 1.0
        while not self._stop.is_set():
            if not self.ffmpeg:
                self.state, self.error = "offline", "The video part of Overwatch is missing."
                return
            with self._lock:
                self._reconfig = False
                url, width, fps = self.address_fn(), self.width, self.fps
            self.state = "connecting"
            got = self._once(url, width, fps)
            if self._stop.is_set():
                return
            if self._reconfig:
                continue
            self.state = "offline"
            if not self.retry:
                return
            delay = 1.0 if got else min(delay * 2, 15.0)
            self._stop.wait(delay)

    def _once(self, url, width, fps):
        try:
            self._proc = p = subprocess.Popen(view_command(self.ffmpeg, url, width, fps), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                              stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        except OSError as e:
            self.error = str(e)
            return False
        last = [time.monotonic()]
        got = False
        done = threading.Event()

        def watchdog():
            while not done.wait(1.0):
                limit = self.stall if got else self.first
                if time.monotonic() - last[0] > limit:
                    self._kill()
                    return
        threading.Thread(target=watchdog, daemon=True).start()
        try:
            while not self._stop.is_set():
                frame = read_ppm(p.stdout)
                if frame is None:
                    break
                got = True
                last[0] = time.monotonic()
                self.frame = frame
                self.seq += 1
                self.state = "live"
        except (ValueError, OSError):
            pass
        finally:
            done.set()
            self._kill()
            try:
                p.wait(3)
                p.stdout.close()
            except (OSError, subprocess.TimeoutExpired):
                pass
        return got


def safe_name(name):
    """A folder name made from a camera name."""
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", (name or "").strip()).strip(". ")
    return n[:60] or "Camera"


def record_command(ffmpeg, url, folder):
    """Copies the camera's own video into 15-minute files (no re-encoding, no extra load) named by the time they started."""
    out = os.path.join(folder, "%Y-%m-%d_%H-%M-%S.mp4")
    return [ffmpeg, "-hide_banner", "-loglevel", "error", *_input_args(url), "-an", "-sn", "-c:v", "copy",
            "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-reset_timestamps", "1", "-strftime", "1",
            "-segment_format", "mp4", "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof", out]


class Recorder:
    """Records one camera. Stop sends ffmpeg a polite 'q' so the last file closes properly."""

    def __init__(self, root, name, address_fn, ffmpeg=None):
        self.folder = os.path.join(root, safe_name(name))
        self.address_fn = address_fn
        self.ffmpeg = ffmpeg or find_ffmpeg()
        self._proc = None
        self.error = ""

    @property
    def active(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        if self.active:
            return True
        if not self.ffmpeg:
            self.error = "The video part of Overwatch is missing."
            return False
        try:
            os.makedirs(self.folder, exist_ok=True)
            self._proc = subprocess.Popen(record_command(self.ffmpeg, self.address_fn(), self.folder), stdin=subprocess.PIPE,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        except OSError as e:
            self.error = str(e)
            return False
        return True

    def stop(self, wait=6.0):
        p = self._proc
        if not p:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(b"q\n")
                    p.stdin.flush()
                except OSError:
                    pass
                try:
                    p.wait(wait)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        finally:
            for f in (p.stdin,):
                try:
                    f.close()
                except (OSError, AttributeError):
                    pass
            self._proc = None


def low_disk(path, need=LOW_DISK_BYTES):
    try:
        os.makedirs(path, exist_ok=True)
        return shutil.disk_usage(path).free < need
    except OSError:
        return False


def prune_recordings(root, days, now=None):
    """Deletes recording files older than `days` days. Returns how many were removed. days <= 0 keeps everything."""
    if days <= 0 or not os.path.isdir(root):
        return 0
    cutoff = (now or time.time()) - days * 86400
    n = 0
    for base, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".mp4"):
                p = os.path.join(base, f)
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.remove(p)
                        n += 1
                except OSError:
                    pass
    return n


def recordings_root():
    return os.path.join(os.path.expanduser("~"), "Downloads", "Cindrix", "Cameras")


def host_port(url):
    """(host, port) a camera address points at, or None."""
    from urllib.parse import urlsplit
    try:
        p = urlsplit(url)
        if not p.hostname:
            return None
        return p.hostname, p.port or {"rtsp": 554, "rtsps": 322, "http": 80, "https": 443}.get(p.scheme, 554)
    except ValueError:
        return None


def reachable(url, timeout=2.0):
    """True when something answers at the camera's address. Used for the on/off dot of cameras that are not on screen."""
    import socket
    hp = host_port(url)
    if not hp:
        return False
    try:
        with socket.create_connection(hp, timeout=timeout):
            return True
    except OSError:
        return False
