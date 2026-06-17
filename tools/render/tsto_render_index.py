"""B1: build a cached sprite-locator index: rgb basename(lower) -> package file
(preferring in-game 'Game' art). Single-threaded list-only scan; gentle on the node."""
import os, io, zipfile, json, time
BASE = "/opt/tsto/static/assets/oct2018-4-35-0-uam5h44a.tstodlc.eamobile.com/netstorage/gameasset/direct/simpsons"
loc = {}            # basename -> pkgfile (relative to BASE)
has_bsv3 = {}       # basename -> bool
t0 = time.time(); npkg = 0
for pkg in sorted(os.listdir(BASE)):
    pdir = os.path.join(BASE, pkg)
    if not os.path.isdir(pdir):
        continue
    npkg += 1
    for fn in os.listdir(pdir):
        if "udio" in fn or not fn.endswith(".zip"):
            continue
        fp = os.path.join(pdir, fn)
        try:
            oz = zipfile.ZipFile(fp)
            if "1" not in oz.namelist():
                continue
            names = zipfile.ZipFile(io.BytesIO(oz.read("1"))).namelist()
        except Exception:
            continue
        rgbs = [os.path.basename(n).lower()[:-4] for n in names if n.lower().endswith(".rgb")]
        bsv = set(os.path.basename(n).lower()[:-5] for n in names if n.lower().endswith(".bsv3"))
        rel = os.path.relpath(fp, BASE)
        prefer = "game" in fn.lower()
        for b in rgbs:
            if b not in loc or (prefer and "game" not in loc[b].lower()):
                loc[b] = rel
            has_bsv3[b] = has_bsv3.get(b, False) or (b in bsv)
json.dump({"loc": loc, "has_bsv3": has_bsv3}, open("/tmp/rgb_index.json", "w"))
open("/tmp/idx.done", "w").write("%d packages, %d sprites, %.0fs\n" % (npkg, len(loc), time.time()-t0))
print("done", npkg, len(loc))
