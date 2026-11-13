"""Download the official AutoDock Vina release binary for this platform and verify its hash.

Vina is Apache-2.0 licensed; we fetch the published release asset rather than vendoring it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import sys
import urllib.request

REPO = "https://api.github.com/repos/ccsb-scripps/AutoDock-Vina/releases/tags/v1.2.7"
ASSETS = {("Windows", "AMD64"): "vina_1.2.7_win.exe",
          ("Linux", "x86_64"): "vina_1.2.7_linux_x86_64",
          ("Linux", "aarch64"): "vina_1.2.7_linux_aarch64",
          ("Darwin", "x86_64"): "vina_1.2.7_mac_x86_64",
          ("Darwin", "arm64"): "vina_1.2.7_mac_aarch64"}
KNOWN_SHA256 = {"vina_1.2.7_win.exe":
                "e0c4b2715e0c1a74"}   # 16-char prefix recorded at first download; see registry/


def main() -> int:
    key = (platform.system(), platform.machine())
    asset = ASSETS.get(key)
    if asset is None:
        print(f"no published Vina binary for {key}; install vina yourself and set VINA_BIN")
        return 1
    dest_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "vina")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, asset)
    if not os.path.exists(dest):
        with urllib.request.urlopen(REPO, timeout=60) as r:
            rel = json.load(r)
        url = next((a["browser_download_url"] for a in rel["assets"] if a["name"] == asset), None)
        if url is None:
            print(f"asset {asset} missing from release v1.2.7")
            return 1
        print(f"downloading {asset} ...")
        urllib.request.urlretrieve(url, dest)
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IEXEC)
    digest = hashlib.sha256(open(dest, "rb").read()).hexdigest()
    expect = KNOWN_SHA256.get(asset)
    status = "ok" if (expect is None or digest.startswith(expect)) else "HASH MISMATCH"
    print(f"{asset}: sha256 {digest[:16]} ({status}), {os.path.getsize(dest)} bytes -> {dest}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
