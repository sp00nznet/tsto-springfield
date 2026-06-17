"""Refresh the town viewer from the CURRENT save: re-read sp00nz, resolve every
building id -> sprite (catalog + _buildings.xml names + explicit overrides),
extract any missing sprites (tstorgb --first, single-sprite, load-checked),
rebuild /opt/tsto/townview/town.json. Re-runnable; gentle on the node."""
import warnings
warnings.filterwarnings('ignore')
import paramiko
import os as _os  # set PVE_PASS + PVE_HOST env
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(_os.environ.get('PVE_HOST','192.168.100.22'), username='root', password=_os.environ["PVE_PASS"], timeout=30)
def run(cmd, t=600):
    _, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8','replace') + e.read().decode('utf-8','replace')

TOWN = "sp00nz"
PROG = r'''
import os, io, zipfile, re, json, glob, shutil, subprocess, collections, sys
from PIL import Image
TOWN=sys.argv[1]
BASE="/opt/tsto/static/assets/oct2018-4-35-0-uam5h44a.tstodlc.eamobile.com/netstorage/gameasset/direct/simpsons"
TSTORGB="/usr/local/bin/tstorgb"
LOC=json.load(open("/tmp/rgb_index.json"))["loc"]
gs=sorted(glob.glob(BASE+"/*/gamescripts-*.zip"))[-1]
inner=zipfile.ZipFile(io.BytesIO(zipfile.ZipFile(gs).read("1")))
def rd(n):
    try: return inner.read(n).decode("utf-8-sig","replace")
    except: return ""

# id -> name from inventory_* AND *_buildings.xml (covers naturals/mountains)
id2name={}
for f in inner.namelist():
    if f.endswith("inventory_buildings.xml") or f.endswith("inventory_decorations.xml"):
        for m in re.finditer(r'<Object\b([^>]*)/?>', rd(f)):
            a=dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            if a.get("id","").isdigit() and a.get("name"): id2name.setdefault(int(a["id"]), a["name"])
for f in inner.namelist():
    if f.endswith("_buildings.xml") or f.endswith("_decorations.xml"):
        for m in re.finditer(r'<(?:Building|Decoration)\b([^>]*?)>', rd(f)):
            a=dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            if a.get("id","").isdigit() and a.get("name"): id2name.setdefault(int(a["id"]), a["name"])
# name -> sprite (assetdata BSv2)
name2sprite={}
for f in inner.namelist():
    if f.endswith("_buildingsassetdata.xml") or f.endswith("_decorationsassetdata.xml"):
        for bm in re.finditer(r'<Building\b[^>]*name="([^"]+)"[^>]*>(.*?)</Building>', rd(f), re.S):
            sm=re.search(r'<BS[vV][23]\b([^>]*)', bm.group(2))
            if sm:
                a=dict(re.findall(r'(\w+)="([^"]*)"', sm.group(1)))
                if a.get("name"): name2sprite.setdefault(bm.group(1), a["name"])

OVR={1:"simpsonshouse",8:"generichouse00",9:"flandershouse"}  # name!=sprite base cases

def candidates(bid):
    out=[]
    if bid in OVR: out.append(OVR[bid].lower())
    nm=id2name.get(bid); spr=name2sprite.get(nm) if nm else None
    for s in (spr, nm):
        if not s: continue
        s=s.lower()
        out += [s, s.replace(" ",""), s.replace("_",""), s.replace("-",""), s+"01", s+"00"]
    return list(dict.fromkeys(out))

# current save
open("/tmp/d.py","w").write('from proto import LandData_pb2;l=LandData_pb2.LandMessage();l.ParseFromString(open("towns/%s","rb").read());import json;print(json.dumps([[b.building,round(b.positionX,2),round(b.positionY,2),int(b.flipped)] for b in l.buildingData]))'%TOWN)
os.system("docker cp /tmp/d.py tsto-server-1:/app/_d.py >/dev/null 2>&1")
raw=subprocess.run(["docker","exec","-w","/app","tsto-server-1","python3","_d.py"],capture_output=True,text=True).stdout
buildings=json.loads([l for l in raw.splitlines() if l.startswith("[")][0])
distinct=collections.Counter(b[0] for b in buildings)
print(f"{TOWN}: {len(buildings)} placements, {len(distinct)} distinct types")

resolve={}; unresolved=[]
for bid,cnt in distinct.most_common():
    hit=None
    for cand in candidates(bid):
        if cand in LOC: hit=cand; break
    if hit: resolve[bid]={"sprite":hit,"pkg":LOC[hit]}
    else: unresolved.append((bid,cnt,id2name.get(bid)))
print(f"resolved {len(resolve)}/{len(distinct)} types")
if unresolved:
    print("UNRESOLVED:", [(b,c,n) for b,c,n in unresolved][:20])

# extract sprites we don't already have (group by package; --first; serial)
SPR="/opt/tsto/townview/sprites"; os.makedirs(SPR,exist_ok=True)
need={}
for bid,info in resolve.items():
    if not os.path.exists(f"{SPR}/{info['sprite']}.png"):
        need.setdefault(info["pkg"], set()).add(info["sprite"])
print("packages to extract from:", len(need), "sprites:", sum(len(v) for v in need.values()))
for pkg,sprset in need.items():
    if os.path.exists("/proc/loadavg"):
        if float(open("/proc/loadavg").read().split()[0])>26:
            print("load high, skipping rest"); break
    IN="/tmp/rf_in";OUT="/tmp/rf_out";TMP="/tmp/rf_tmp"
    for d in (IN,OUT,TMP): shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
    try: zipfile.ZipFile(io.BytesIO(zipfile.ZipFile(os.path.join(BASE,pkg)).read("1"))).extractall(TMP)
    except Exception as e: print("x",pkg,e); continue
    for spr in sprset:
        for ext in (".rgb",".bsv3",".bcell"):
            s=os.path.join(TMP,spr+ext)
            if os.path.exists(s): shutil.copy(s,IN)
    subprocess.run([TSTORGB,"--first",IN,OUT],capture_output=True,text=True)
    for spr in sprset:
        cs=[p for p in glob.glob(f"{OUT}/{spr}/**/*.png",recursive=True)] or [p for p in glob.glob(f"{OUT}/**/*.png",recursive=True) if spr in p.lower()]
        if cs: shutil.copy(max(cs,key=os.path.getsize), f"{SPR}/{spr}.png")
    shutil.rmtree(TMP,ignore_errors=True)

# rebuild town.json
have=set(os.path.splitext(f)[0] for f in os.listdir(SPR) if f.endswith(".png"))
out=[]
for bid,x,y,flip in buildings:
    info=resolve.get(bid)
    if info and info["sprite"] in have:
        w,h=Image.open(f"{SPR}/{info['sprite']}.png").size
        out.append({"sprite":info["sprite"],"x":x,"y":y,"flip":flip,"w":w,"h":h})
json.dump({"meta":{"name":TOWN,"tileW":24,"tileH":12,"count":len(out)},"buildings":out},
          open("/opt/tsto/townview/town.json","w"))
print(f"town.json rebuilt: {len(out)}/{len(buildings)} placements, {len(have)} sprite types")
'''
with c.open_sftp() as s:
    with s.file('/tmp/rf.py','w') as f: f.write(PROG)
run("pct push 127 /tmp/rf.py /tmp/rf.py")
print("load before:", run("cat /proc/loadavg").strip())
print(run(f"pct exec 127 -- python3 /tmp/rf.py {TOWN}", t=600))
print("load after:", run("cat /proc/loadavg").strip())
c.close()
