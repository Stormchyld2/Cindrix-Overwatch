"""CI helper: downloads a Windows ffmpeg (BtbN FFmpeg-Builds, LGPL build, no GPL parts) into ffmpeg_bundle/.

Watchtower uses it to show and record camera video. If the download fails this exits non-zero and the build carries on
without it; Watchtower then says the video part is missing, and everything else works."""
import io
import os
import sys
import urllib.request
import zipfile

URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip"


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": "CindrixOverwatch-build"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    os.makedirs("ffmpeg_bundle", exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        exe = next(n for n in names if n.endswith("/bin/ffmpeg.exe"))
        with open("ffmpeg_bundle/ffmpeg.exe", "wb") as f:
            f.write(z.read(exe))
        for n in names:
            base = n.rsplit("/", 1)[-1].upper()
            if base.startswith(("LICENSE", "COPYING")) and not n.endswith("/"):
                with open("ffmpeg_bundle/" + n.rsplit("/", 1)[-1], "wb") as f:
                    f.write(z.read(n))
    print("ffmpeg ready:", os.path.getsize("ffmpeg_bundle/ffmpeg.exe"), "bytes")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("ffmpeg download failed:", e)
        sys.exit(1)
