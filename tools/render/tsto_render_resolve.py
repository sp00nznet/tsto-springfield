"""B2: resolve sp00nz distinct building ids -> sprite basename + package file,
using the cached index + gamescripts catalog. Pure data; gentle. Writes resolve.json."""
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
import os, io, zipfile, re, json, glob, collections, subprocess
BASE="/opt/tsto/static/assets/oct2018-4-35-0-uam5h44a.tstodlc.eamobile.com/netstorage/gameasset/direct/simpsons"
idx=json.load(open("/tmp/rgb_index.json")); LOC=idx["loc"]
gs=sorted(glob.glob(BASE+"/*/gamescripts-*.zip"))[-1]
inner=zipfile.ZipFile(io.BytesIO(zipfile.ZipFile(gs).read("1")))
def rd(n):
    try: return inner.read(n).decode("utf-8-sig","replace")
    except: return ""

id2name={}
for f in inner.namelist():
    if f.endswith("inventory_buildings.xml") or f.endswith("inventory_decorations.xml"):
        for m in re.finditer(r'<Object\b([^>]*)/?>', rd(f)):
            a=dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            if a.get("id","").isdigit() and a.get("name"): id2name[int(a["id"])]=a["name"]
name2sprite={}
for f in inner.namelist():
    if f.endswith("_buildingsassetdata.xml") or f.endswith("_decorationsassetdata.xml"):
        for bm in re.finditer(r'<Building\b[^>]*name="([^"]+)"[^>]*>(.*?)</Building>', rd(f), re.S):
            sm=re.search(r'<BS[vV][23]\b([^>]*)', bm.group(2))
            if sm:
                a=dict(re.findall(r'(\w+)="([^"]*)"', sm.group(1)))
                if a.get("name"): name2sprite[bm.group(1)]=a["name"]

# sp00nz buildings
open("/tmp/d.py","w").write('from proto import LandData_pb2;l=LandData_pb2.LandMessage();l.ParseFromString(open("towns/sp00nz","rb").read());import json;print(json.dumps([[b.building,round(b.positionX,2),round(b.positionY,2),int(b.flipped)] for b in l.buildingData]))')
os.system("docker cp /tmp/d.py tsto-server-1:/app/_d.py >/dev/null 2>&1")
raw=subprocess.run(["docker","exec","-w","/app","tsto-server-1","python3","_d.py"],capture_output=True,text=True).stdout
buildings=json.loads([l for l in raw.splitlines() if l.startswith("[")][0])

def cands(nm, spr):
    out=[]
    for s in [spr, nm]:
        if not s: continue
        s=s.lower()
        out += [s, s.replace(" ",""), s.replace("_",""), s.replace("-","")]
    return list(dict.fromkeys(out))

distinct=collections.Counter(b[0] for b in buildings)
resolve={}; rows=[]
for bid,cnt in distinct.most_common():
    nm=id2name.get(bid); spr=name2sprite.get(nm) if nm else None
    hit=None
    for cand in cands(nm, spr):
        if cand in LOC: hit=cand; break
    rows.append((bid,cnt,nm,spr,hit,LOC.get(hit,"") if hit else ""))
    if hit: resolve[str(bid)]={"sprite":hit,"pkg":LOC[hit]}
ok=sum(1 for r in rows if r[4]); inst=sum(c for _,c,_,_,h,_ in rows if h)
print(f"distinct resolved: {ok}/{len(rows)}  |  instances covered: {inst}/{len(buildings)}")
for bid,cnt,nm,spr,hit,pkg in rows:
    print(f"  id {bid:>7} x{cnt:<4} name={nm} sprite={spr} -> {hit or 'UNRESOLVED'}  {os.path.basename(pkg) if pkg else ''}")
json.dump({"buildings":buildings,"resolve":resolve}, open("/tmp/resolve.json","w"))
print("wrote /tmp/resolve.json")
'''
with c.open_sftp() as s:
    with s.file('/tmp/b2.py','w') as f: f.write(PROG)
run("pct push 127 /tmp/b2.py /tmp/b2.py")
print(run("pct exec 127 -- python3 /tmp/b2.py", t=300))
c.close()
