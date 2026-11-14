"""Fetch wheels from PyPI and unzip into a target dir (bypasses pip temp unpack).

沙箱里 pip 的临时解包目录会被拒（PermissionError），所以这里自己下 wheel 再解压。
大文件（torch 120MB+）走 Range 断点续传 + 重试，网络被掐也能接着下。
"""
import json, os, sys, time, urllib.request, zipfile, pathlib

TARGET = pathlib.Path(sys.argv[1])
WHEEL_DIR = pathlib.Path(sys.argv[2])
PACKAGES = sys.argv[3:]
TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
PLAT = "win_amd64"
CHUNK = 1 << 18


def best_wheel(files):
    cands = []
    for f in files:
        if f["packagetype"] != "bdist_wheel":
            continue
        n = f["filename"]
        ok = n.endswith("py3-none-any.whl") or n.endswith("py2.py3-none-any.whl") or (
            TAG in n and (PLAT in n or "none-any" in n)
        )
        if ok:
            cands.append(f)
    # prefer a wheel matching this interpreter, then universal
    cands.sort(key=lambda f: (TAG not in f["filename"], "none-any" not in f["filename"], f["filename"]))
    return cands[0] if cands else None


def skip_marker(spec):
    s = spec.lower()
    if "extra" in s:
        return True
    if "platform_system" in s and "windows" not in s:
        return True
    if "sys_platform" in s and "win32" not in s:
        return True
    if "platform_machine" in s and "amd64" not in s and "x86_64" not in s:
        return True
    return False


def download(url, path, expected=None, attempts=8):
    for attempt in range(1, attempts + 1):
        have = path.stat().st_size if path.exists() else 0
        if expected and have >= expected:
            return
        req = urllib.request.Request(url)
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                partial = getattr(r, "status", 200) == 206
                mode = "ab" if partial and have else "wb"
                if mode == "wb":
                    have = 0
                with open(path, mode) as f:
                    while True:
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
        except Exception as exc:  # noqa: BLE001 - 网络抖动一律重试
            print(f"  retry {attempt}/{attempts} for {path.name}: {type(exc).__name__}", file=sys.stderr)
            time.sleep(min(2 * attempt, 10))
            continue
        size = path.stat().st_size if path.exists() else 0
        if expected is None or size >= expected:
            return
        print(f"  short read {size}/{expected} for {path.name}, retrying", file=sys.stderr)
        time.sleep(min(2 * attempt, 10))
    raise SystemExit(f"download failed after retries: {url}")


WHEEL_DIR.mkdir(parents=True, exist_ok=True)
TARGET.mkdir(parents=True, exist_ok=True)
seen, order = set(), []


def resolve(name):
    key = name.lower()
    if key in seen:
        return
    seen.add(key)
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=60) as r:
        meta = json.load(r)
    info = meta["info"]
    wheel = best_wheel(meta["urls"])
    if wheel is None:
        raise SystemExit(f"no wheel for {name}")
    path = WHEEL_DIR / wheel["filename"]
    download(wheel["url"], path, wheel.get("size"))
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(TARGET)
    except zipfile.BadZipFile:
        print(f"  corrupt wheel {path.name}, redownloading", file=sys.stderr)
        path.unlink()
        download(wheel["url"], path, wheel.get("size"))
        with zipfile.ZipFile(path) as z:
            z.extractall(TARGET)
    order.append(name)
    for req in info.get("requires_dist") or []:
        if skip_marker(req):
            continue
        dep = req.split(";")[0].strip()
        for sep in ("[", " ", "(", "<", ">", "=", "!", "~"):
            dep = dep.replace(sep, "|")
        base = dep.split("|")[0].strip()
        if base and base.lower() not in ("python",):
            resolve(base)


for p in PACKAGES:
    resolve(p)
print("installed:", ", ".join(order))
