"""B3: extract ONLY the resolved sprites (single-sprite, tstorgb --first => light),
write /opt/tsto/townview/{sprites/*.png, town.json}. Load-checked + serial."""
import warnings, time
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
R=json.load(open("/tmp/resolve.json")); resolve=R["resolve"]; buildings=R["buildings"]
OUTDIR="/opt/tsto/townview"; SPR=OUTDIR+"/sprites"
shutil.rmtree(OUTDIR,ignore_errors=True); os.makedirs(SPR)

# group target sprites by package
by_pkg={}
for bid,info in resolve.items():
    by_pkg.setdefault(info["pkg"], set()).add(info["sprite"])

dims={}
for pkg, sprset in by_pkg.items():
    IN="/tmp/b3in"; OUT="/tmp/b3out"; TMP="/tmp/b3tmp"
    for d in (IN,OUT,TMP): shutil.rmtree(d,ignore_errors=True); os.makedirs(d)
    try:
        oz=zipfile.ZipFile(os.path.join(BASE,pkg))
        zipfile.ZipFile(io.BytesIO(oz.read("1"))).extractall(TMP)
    except Exception as e:
        print("extract fail",pkg,e); continue
    # copy ONLY the target sprite files (rgb+bsv3) -> tiny input
    for spr in sprset:
        for ext in (".rgb",".bsv3",".bcell"):
            src=os.path.join(TMP, spr+ext)
            if os.path.exists(src): shutil.copy(src, IN)
    # one frame each => light
    subprocess.run([TSTORGB,"--first",IN,OUT],capture_output=True,text=True)
    for spr in sprset:
        cand=[p for p in glob.glob(f"{OUT}/{spr}/**/*.png",recursive=True)]
        if not cand: cand=glob.glob(f"{OUT}/**/*.png",recursive=True)
        cand=[p for p in cand if os.path.basename(os.path.dirname(os.path.dirname(p)))==spr or spr in p.lower()]
        if not cand: print("  no png for",spr); continue
        big=max(cand,key=os.path.getsize)
        shutil.copy(big, f"{SPR}/{spr}.png")
        dims[spr]=Image.open(big).size
    shutil.rmtree(TMP,ignore_errors=True)
    print("pkg done:", os.path.basename(pkg), "sprites:", sorted(s for s in sprset if s in dims))

# build town.json (all placements whose sprite extracted)
out=[]
for bid,x,y,flip in buildings:
    info=resolve.get(str(bid))
    if info and info["sprite"] in dims:
        w,h=dims[info["sprite"]]
        out.append({"sprite":info["sprite"],"x":x,"y":y,"flip":flip,"w":w,"h":h})
meta={"name":"sp00nz","tileW":24,"tileH":12,"count":len(out)}
json.dump({"meta":meta,"buildings":out}, open(OUTDIR+"/town.json","w"))
print(f"town.json: {len(out)}/{len(buildings)} placements, {len(dims)} sprite types: {sorted(dims)}")
'''
with c.open_sftp() as s:
    with s.file('/tmp/b3.py','w') as f: f.write(PROG)
run("pct push 127 /tmp/b3.py /tmp/b3.py")
print("load before:", run("cat /proc/loadavg").strip())
print(run("pct exec 127 -- python3 /tmp/b3.py", t=300))
print("load after:", run("cat /proc/loadavg").strip())
print("townview dir:", run("pct exec 127 -- bash -lc 'ls -la /opt/tsto/townview/sprites | head; echo ---; ls -la /opt/tsto/townview/town.json'").strip())
c.close()
