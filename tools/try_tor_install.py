"""CI experiment: which command line makes the Tor Browser portable exe unpack quietly?"""
import os, subprocess, tempfile, time
from cindrix_overwatch import torbrowser as t

v, name, want = t.latest()
data = t._get(f"{t.BASE}{v}/{name}", timeout=900)
base = tempfile.mkdtemp()
exe = os.path.join(base, name)
open(exe, "wb").write(data)
print("size", len(data), "head", data[:2], "7z sig at", data.find(b"7z\xbc\xaf\x27\x1c"))
variants = [["-y"], ["-y", "-o{d}"], ["-o{d}", "-y"], ["/S"], ["/S", "/D={d}"], ["-y", "-gm2", "-o{d}"], ["x", "-y", "-o{d}"]]
for i, v_ in enumerate(variants):
    d = os.path.join(base, f"out{i}")
    os.makedirs(d)
    args = [exe] + [a.format(d=d) for a in v_]
    p = subprocess.Popen(args, cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 60 and p.poll() is None:
        time.sleep(2)
    left = p.poll() is None
    if left:
        p.kill()
    found = [os.path.join(b, f)[len(base):] for b, _, fs in os.walk(d) for f in fs if f.lower() == "firefox.exe"]
    anything = sum(len(fs) for _, _, fs in os.walk(d))
    print(i, v_, "running_after_60s" if left else f"exit {p.returncode}", "files", anything, "firefox", found)
    if found:
        break
