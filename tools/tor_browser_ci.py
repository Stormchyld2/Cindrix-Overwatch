"""CI: installs the real Tor Browser, then checks it starts (firefox --version) without hanging the job."""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.getcwd())
from cindrix_overwatch import tor, torbrowser as t

d = tempfile.mkdtemp()
p = t.install(d, print)
print("INSTALLED", p, os.path.getsize(p), flush=True)
out = os.path.join(d, "launch.txt")
with open(out, "w") as f:
    proc = subprocess.Popen([p, "--version"], cwd=os.path.dirname(p), env=tor.clean_env(), stdout=f, stderr=subprocess.STDOUT)
    t0 = time.time()
    while proc.poll() is None and time.time() - t0 < 60:
        time.sleep(1)
    rc = proc.poll()
    if rc is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30)
print("LAUNCH_CHECK exit", rc, open(out, errors="replace").read().strip()[:300], flush=True)
