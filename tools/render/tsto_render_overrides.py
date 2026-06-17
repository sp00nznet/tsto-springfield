"""Augment resolution with explicit overrides for buildings whose inventory name
!= rgb sprite name (base houses, mountains). Extract the new sprites (--first,
single-sprite), rebuild town.json. Gentle on the node."""
import warnings
warnings.filterwarnings('ignore')
import paramiko
import os as _os  # set PVE_PASS + PVE_HOST env
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(_os.environ.get('PVE_HOST','192.168.100.22'), username='root', password=_os.environ["PVE_PASS"], timeout=30)
def run(cmd, t=300):
    _, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8','replace') + e.read().decode('utf-8','replace')

PROG = r'''
import os, io, zipfile, glob, shutil, subprocess, json
from PIL import Image
BASE="/opt/tsto/static/assets/oct2018-4-35-0-uam5h44a.tstodlc.eamobile.com/netstorage/gameasset/direct/simpsons"
TSTORGB="/usr/local/bin/tstorgb"
LOC=json.load(open("/tmp/rgb_index.json"))["loc"]
R=json.load(open("/tmp/resolve.json")); resolve=R["resolve"]; buildings=R["buildings"]

# explicit id -> candidate sprite names (first that exists in the index wins)
OVR = {
 1:["simpsonshouse"], 8:["generichouse00","generichouse01"], 9:["flandershouse"],
 105020:["mountain01","mountain00","mountainrange01","mountain"],
 105021:["mountain02","mountainrange02"], 105022:["mountain03","mountainrange03"],
 105024:["mountain04","mountain05","mountainrange04"],
}
added={}
for bid,cands in OVR.items():
    for cand in cands:
        if cand in LOC:
            resolve[str(bid)]={"sprite":cand,"pkg":LOC[cand]}; added[bid]=cand; break
    else:
        print("  no sprite for id",bid,"tried",cands)
print("overrides applied:", added)

# which sprites still need extracting (not already present)
SPR="/opt/tsto/townview/sprites"
need={}
for bid,info in resolve.items():
    if not os.path.exists(f"{SPR}/{info['sprite']}.png"):
        need.setdefault(info["pkg"], set()).add(info["sprite"])
print("sprites to extract:", {os.path.basename(k):sorted(v) for k,v in need.items()})

dims={}
for pkg, sprset in need.items():
    IN="/tmp/aug_in"; OUT="/tmp/aug_out"; TMP="/tmp/aug_tmp"
    for d in (IN,OUT,TMP): shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
    zipfile.ZipFile(io.BytesIO(zipfile.ZipFile(os.path.join(BASE,pkg)).read("1"))).extractall(TMP)
    for spr in sprset:
        for ext in (".rgb",".bsv3",".bcell"):
            s=os.path.join(TMP,spr+ext)
            if os.path.exists(s): shutil.copy(s,IN)
    subprocess.run([TSTORGB,"--first",IN,OUT],capture_output=True,text=True)
    for spr in sprset:
        cand=glob.glob(f"{OUT}/{spr}/**/*.png",recursive=True) or glob.glob(f"{OUT}/**/*.png",recursive=True)
        cand=[p for p in cand if spr in p.lower()]
        if not cand: print("  NO OUTPUT",spr); continue
        big=max(cand,key=os.path.getsize); shutil.copy(big,f"{SPR}/{spr}.png")
        print("  extracted",spr,Image.open(big).size)
    shutil.rmtree(TMP,ignore_errors=True)

# rebuild town.json with every placement that now has a sprite file
have=set(os.path.splitext(f)[0] for f in os.listdir(SPR) if f.endswith(".png"))
out=[]
for bid,x,y,flip in buildings:
    info=resolve.get(str(bid))
    if info and info["sprite"] in have:
        w,h=Image.open(f"{SPR}/{info['sprite']}.png").size
        out.append({"sprite":info["sprite"],"x":x,"y":y,"flip":flip,"w":w,"h":h})
meta={"name":"sp00nz","tileW":24,"tileH":12,"count":len(out)}
json.dump({"meta":meta,"buildings":out}, open("/opt/tsto/townview/town.json","w"))
import collections
print(f"town.json: {len(out)}/{len(buildings)} placements, {len(have)} sprite types")
print("types:", sorted(have))
'''
with c.open_sftp() as s:
    with s.file('/tmp/aug.py','w') as f: f.write(PROG)
run("pct push 127 /tmp/aug.py /tmp/aug.py")
print("load before:", run("cat /proc/loadavg").strip())
print(run("pct exec 127 -- python3 /tmp/aug.py", t=300))
print("load after:", run("cat /proc/loadavg").strip())
c.close()
