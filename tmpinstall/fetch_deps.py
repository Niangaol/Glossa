"""Fetch pure wheels from PyPI and unzip into a target dir (bypasses pip temp unpack)."""
import json, sys, urllib.request, zipfile, pathlib, sysconfig

TARGET = pathlib.Path(sys.argv[1])
WHEEL_DIR = pathlib.Path(sys.argv[2])
PACKAGES = sys.argv[3:]
TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
PLAT = "win_amd64"

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
    # prefer platform-specific compiled, else universal
    cands.sort(key=lambda f: (("none-any" not in f["filename"]), f["filename"]))
    return cands[0] if cands else None

WHEEL_DIR.mkdir(parents=True, exist_ok=True)
TARGET.mkdir(parents=True, exist_ok=True)
seen, order = set(), []
def resolve(name):
    if name.lower() in seen:
        return
    seen.add(name.lower())
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=60) as r:
        meta = json.load(r)
    info = meta["info"]
    wheel = best_wheel(meta["urls"])
    if wheel is None:
        raise SystemExit(f"no wheel for {name}")
    path = WHEEL_DIR / wheel["filename"]
    if not path.exists():
        with urllib.request.urlopen(wheel["url"], timeout=120) as r, open(path, "wb") as f:
            f.write(r.read())
    with zipfile.ZipFile(path) as z:
        z.extractall(TARGET)
    order.append(name)
    for req in info.get("requires_dist") or []:
        if "; extra" in req.lower() or "extra ==" in req.lower():
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
