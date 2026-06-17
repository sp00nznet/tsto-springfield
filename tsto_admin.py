"""TSTO admin panel — added to the d-fens server in-process via register_admin(server).

Not part of upstream d-fens. deploy_tsto.py uploads this file, mounts it into the
container, and patches tsto_server.py to (a) read the donut balance from
server.donut_balance and (b) call register_admin(self) once routes are set up.

Provides /admin: editable donut balance, a towns overview (level / cash / building
& character counts / last-saved), switch-active-town, and the play-mode selector.
Town stats are read-only (parsed from the save protobufs). Reachable on the same
port as the game server (9000), e.g. http://<tailscale-ip>:9000/admin.
"""
import os
import re
import sys
import time

from flask import request, redirect, render_template_string, send_from_directory, Response

from proto import LandData_pb2

TOWNVIEW_DIR = "townview"   # /app/townview, mounted from /opt/tsto/townview

DEFAULT_DONUTS = 1234567
DONUT_FILE = "towns/.donut_balance"   # persisted on the towns volume
CONFIG_FILE = "config.json"

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>TSTO Admin</title>
<style>
  body{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#10131a;color:#e8e8ea;margin:0;padding:24px}
  h1{color:#f7c843;margin:0 0 4px} .sub{color:#8b93a7;margin:0 0 24px}
  .card{background:#1a1f2b;border:1px solid #2a3142;border-radius:10px;padding:18px 20px;margin:0 0 20px;max-width:980px}
  .card h2{margin:0 0 12px;font-size:1.05em;color:#d64161}
  input[type=number],select{background:#0e1118;color:#e8e8ea;border:1px solid #38415a;border-radius:6px;padding:7px 9px;font-size:1em}
  button{background:#d64161;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:.95em;cursor:pointer}
  button:hover{background:#e3527040}  button.set{background:#2a3142}
  button:hover{filter:brightness(1.1)}
  table{border-collapse:collapse;width:100%;max-width:980px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #232a39}
  th{color:#8b93a7;font-weight:600;font-size:.85em;text-transform:uppercase;letter-spacing:.04em}
  tr.active td{background:#1d2433}
  .badge{background:#f7c843;color:#10131a;border-radius:5px;padding:1px 7px;font-size:.8em;font-weight:700;margin-left:6px}
  .mono{font-variant-numeric:tabular-nums}
  .err{color:#e0666e;font-size:.85em}
  a{color:#f7c843}
</style></head><body>
<h1>🍩 TSTO Admin</h1>
<p class="sub">{{host}} · active town: <b>{{active}}</b> · <a href="/admin/townview" style="color:#f7c843">🏙 isometric town viewer (beta)</a></p>

<div class="card">
  <h2>Donuts</h2>
  <form method="post" action="/admin/donuts">
    <input type="number" name="donuts" value="{{donuts}}" min="0" max="2000000000" style="width:180px">
    <button type="submit">Save donuts</button>
    <span class="sub" style="margin-left:10px">Server returns this balance to every client. Takes effect next time the game reads currency.</span>
  </form>
</div>

<div class="card">
  <h2>Towns</h2>
  <table>
    <tr><th></th><th>Town</th><th>Level</th><th>Cash</th><th>Buildings</th><th>Characters</th><th>Last saved</th><th>Size</th><th></th></tr>
    {% for t in towns %}
    <tr class="{{ 'active' if t.name==active else '' }}">
      <td>{{ '▶' if t.name==active else '' }}</td>
      <td><b>{{t.name}}</b>{% if t.name==active %}<span class="badge">active</span>{% endif %}</td>
      <td class="mono">{{t.level}}</td>
      <td class="mono">{{t.money}}</td>
      <td class="mono">{{t.buildings}}</td>
      <td class="mono">{{t.chars}}</td>
      <td class="mono">{{t.mtime}}</td>
      <td class="mono">{{t.size_kb}} KB</td>
      <td>{% if t.error %}<span class="err">{{t.error}}</span>{% else %}
        <a href="/admin/map?town={{t.name}}"><button class="set" type="button">🗺 map</button></a>
        {% if t.name!=active %}<form method="post" action="/admin/active-town" style="display:inline">
          <input type="hidden" name="town" value="{{t.name}}">
          <button class="set" type="submit">Set active</button>
        </form>{% endif %}{% endif %}</td>
    </tr>
    {% endfor %}
  </table>
  <p class="sub">Switching loads that town immediately and persists it as the default. Do it while not actively playing.</p>
</div>

<div class="card">
  <h2>Edit town (cash / level)</h2>
  <form method="post" action="/admin/edit-town">
    <label>Town
      <select name="town">
        {% for t in towns %}<option value="{{t.name}}" {{ 'selected' if t.name==active else '' }}>{{t.name}}</option>{% endfor %}
      </select>
    </label>
    &nbsp; <label>Cash $ <input type="number" name="money" min="0" max="2000000000" placeholder="unchanged" style="width:140px"></label>
    &nbsp; <label>Level <input type="number" name="level" min="1" max="939" placeholder="unchanged" style="width:90px"></label>
    &nbsp; <button type="submit">Save changes</button>
  </form>
  <p class="sub">Writes directly into the save file. <b>Edit while logged OUT of that town</b> (the game overwrites the
  server on its next sync), then reopen the app to pull the new values. Level sets level+visualLevel; XP isn't recalculated, so the XP bar may look off until you next level up.</p>
</div>

{% if play_modes %}
<div class="card">
  <h2>Play mode / event</h2>
  <form method="post" action="/admin/playmode">
    <select name="playmode">
      {% for pid,label in play_modes %}
      <option value="{{pid}}" {{ 'selected' if pid==current_play_mode else '' }}>{{label}}</option>
      {% endfor %}
    </select>
    <button type="submit">Apply</button>
  </form>
</div>
{% endif %}
<p class="sub">Game dashboard (play-mode only): <a href="/dashboard">/dashboard</a></p>
</body></html>"""


def _read_donuts():
    try:
        return int(open(DONUT_FILE).read().strip())
    except Exception:
        return DEFAULT_DONUTS


def _town_rows(towns_dir):
    rows = []
    try:
        names = sorted(os.listdir(towns_dir))
    except Exception:
        names = []
    for name in names:
        if name.startswith('.'):
            continue
        path = os.path.join(towns_dir, name)
        if not os.path.isfile(path):
            continue
        st = os.stat(path)
        row = {'name': name, 'size_kb': st.st_size // 1024,
               'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime)),
               'level': '?', 'money': '?', 'buildings': '?', 'chars': '?', 'error': ''}
        try:
            land = LandData_pb2.LandMessage()
            land.ParseFromString(open(path, 'rb').read())
            row['level'] = land.userData.level
            row['money'] = land.userData.money
            row['buildings'] = len(land.buildingData)
            row['chars'] = len(land.characterData)
        except Exception as e:
            row['error'] = ('parse error: ' + str(e))[:40]
        rows.append(row)
    return rows


MAP_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{{town}} — map</title>
<style>
  html,body{margin:0;height:100%;background:#0c0f16;color:#e8e8ea;font-family:system-ui,Segoe UI,Arial,sans-serif;overflow:hidden}
  #bar{position:fixed;top:0;left:0;right:0;height:46px;display:flex;align-items:center;gap:14px;padding:0 16px;
       background:#141925cc;border-bottom:1px solid #2a3142;backdrop-filter:blur(4px);z-index:10}
  #bar b{color:#f7c843} #bar a{color:#f7c843;text-decoration:none} .pill{color:#8b93a7;font-size:.9em}
  button{background:#2a3142;color:#e8e8ea;border:0;border-radius:6px;padding:6px 11px;cursor:pointer}
  button:hover{filter:brightness(1.2)}
  #map{position:fixed;inset:46px 0 0 0}
  svg{width:100%;height:100%;display:block;cursor:grab;background:radial-gradient(circle at 50% 40%,#16203a,#0c0f16)}
  svg.drag{cursor:grabbing}
</style></head><body>
<div id="bar">
  <a href="/admin">← admin</a>
  <b>{{town}}</b>
  <span class="pill">{{nb}} buildings · {{nc}} characters</span>
  <span style="flex:1"></span>
  <button onclick="z(1.25)">+</button><button onclick="z(0.8)">−</button><button onclick="reset()">reset</button>
  <span class="pill">drag to pan · scroll to zoom · hover for ID</span>
</div>
<div id="map">
  <svg id="svg" viewBox="{{vb}}" preserveAspectRatio="xMidYMid meet">
    {{body|safe}}
  </svg>
</div>
<script>
const svg=document.getElementById('svg');
const VB0="{{vb}}".split(' ').map(Number);
let vb=VB0.slice();
function apply(){svg.setAttribute('viewBox',vb.join(' '));}
function reset(){vb=VB0.slice();apply();}
function z(f){ // zoom about center
  const cx=vb[0]+vb[2]/2, cy=vb[1]+vb[3]/2;
  vb[2]/=f; vb[3]/=f; vb[0]=cx-vb[2]/2; vb[1]=cy-vb[3]/2; apply();
}
svg.addEventListener('wheel',e=>{e.preventDefault();
  const r=svg.getBoundingClientRect();
  const mx=vb[0]+((e.clientX-r.left)/r.width)*vb[2];
  const my=vb[1]+((e.clientY-r.top)/r.height)*vb[3];
  const f=e.deltaY<0?1.12:0.893;
  vb[2]/=f; vb[3]/=f;
  vb[0]=mx-((e.clientX-r.left)/r.width)*vb[2];
  vb[1]=my-((e.clientY-r.top)/r.height)*vb[3];
  apply();
},{passive:false});
let drag=false,px,py;
svg.addEventListener('mousedown',e=>{drag=true;px=e.clientX;py=e.clientY;svg.classList.add('drag');});
window.addEventListener('mouseup',()=>{drag=false;svg.classList.remove('drag');});
window.addEventListener('mousemove',e=>{ if(!drag)return;
  const r=svg.getBoundingClientRect();
  vb[0]-=(e.clientX-px)*(vb[2]/r.width);
  vb[1]-=(e.clientY-py)*(vb[3]/r.height);
  px=e.clientX;py=e.clientY;apply();
});
</script></body></html>"""


def _town_map(towns_dir, town):
    """Return (viewbox_str, n_buildings, n_chars, svg_body) for a schematic
    top-down plot of building + character positions. No art — just placement."""
    land = LandData_pb2.LandMessage()
    land.ParseFromString(open(os.path.join(towns_dir, town), 'rb').read())
    bs = list(land.buildingData)
    cs = list(land.characterData)
    xs = [b.positionX for b in bs] + [c.positionX for c in cs]
    ys = [b.positionY for b in bs] + [c.positionY for c in cs]
    if not xs:
        return "0 0 100 100", 0, 0, ''
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    pad = 6
    vb = "%.1f %.1f %.1f %.1f" % (minx - pad, miny - pad,
                                  (maxx - minx) + 2 * pad, (maxy - miny) + 2 * pad)
    parts = []
    for b in bs:
        hue = (b.building * 47) % 360
        parts.append(
            '<rect x="%.1f" y="%.1f" width="2.6" height="2.6" rx="0.5" '
            'fill="hsl(%d,58%%,56%%)" stroke="#00000055" stroke-width="0.15">'
            '<title>building %d · state %d · subland %d · (%.0f,%.0f)</title></rect>'
            % (b.positionX, b.positionY, hue, b.building, b.buildState, b.subLandID,
               b.positionX, b.positionY))
    for c in cs:
        parts.append(
            '<circle cx="%.1f" cy="%.1f" r="1.4" fill="#ffd23f" stroke="#00000088" '
            'stroke-width="0.2"><title>character %d</title></circle>'
            % (c.positionX + 1.3, c.positionY + 1.3, c.character))
    return vb, len(bs), len(cs), "\n".join(parts)


def _set_config_active_town(town):
    """Persist active_town into config.json (text sub to preserve formatting)."""
    try:
        s = open(CONFIG_FILE).read()
        s2 = re.sub(r'("active_town"\s*:\s*")[^"]*(")', r'\g<1>' + town + r'\2', s, count=1)
        if s2 != s:
            open(CONFIG_FILE, 'w').write(s2)
    except Exception:
        pass


TOWNVIEW_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Springfield viewer</title>
<style>
 html,body{margin:0;height:100%;background:#0c0f16;overflow:hidden;font-family:system-ui,Segoe UI,Arial}
 #bar{position:fixed;top:0;left:0;right:0;height:44px;display:flex;align-items:center;gap:14px;padding:0 16px;
      background:#141925cc;border-bottom:1px solid #2a3142;color:#e8e8ea;z-index:10;backdrop-filter:blur(4px)}
 #bar b{color:#f7c843} #bar a{color:#f7c843;text-decoration:none} .pill{color:#8b93a7;font-size:.9em}
 button{background:#2a3142;color:#e8e8ea;border:0;border-radius:6px;padding:6px 11px;cursor:pointer}
 button:hover{filter:brightness(1.25)} #cv{position:fixed;inset:44px 0 0 0}
</style></head><body>
<div id="bar"><a href="/admin">&larr; admin</a><b id="title">Springfield</b>
 <span class="pill" id="stat">loading&hellip;</span><span style="flex:1"></span>
 <button onclick="tg()">flip mountains</button><span class="pill" id="ori"></span><span style="flex:1"></span>
 <button onclick="fit()">fit</button><button onclick="zoom(1.25)">+</button><button onclick="zoom(0.8)">&minus;</button>
 <span class="pill">drag=pan &middot; wheel=zoom</span></div>
<div id="cv"></div>
<script src="https://cdn.jsdelivr.net/npm/pixi.js@7.4.2/dist/pixi.min.js"></script>
<script>
(async () => {
 const host=document.getElementById('cv');
 const app=new PIXI.Application({background:'#7eb65c',antialias:true,resizeTo:host});
 host.appendChild(app.view);
 const world=new PIXI.Container(); world.sortableChildren=true; app.stage.addChild(world);
 const town=await (await fetch('/admin/townview/town.json')).json();
 const M=town.meta||{}, TW=M.tileW||24, TH=M.tileH||12;
 document.getElementById('title').textContent=(M.name||'Springfield')+' town';
 const names=[...new Set(town.buildings.map(b=>b.sprite))], tex={};
 await Promise.all(names.map(async n=>{try{tex[n]=await PIXI.Assets.load('/admin/townview/sprites/'+n+'.png');}catch(e){tex[n]=null;}}));
 // orient 4 (confirmed correct positions): sx=(x+y), sy=(y-x).
 // Only the mountain sprites are drawn mirrored for this edge -> flip just those.
 let mtnFlip=1;
 const isMtn = n => n.indexOf('mountain')>=0;
 const items=[];
 for(const b of town.buildings){ const t=tex[b.sprite]; if(!t)continue;
   const sp=new PIXI.Sprite(t); sp.anchor.set(0.5,1.0); world.addChild(sp); items.push({sp,b}); }
 function layout(){
   for(const {sp,b} of items){
     sp.x=(b.x+b.y)*TW; sp.y=(b.y-b.x)*TH; sp.zIndex=sp.y;
     let mir=(b.flip?1:0); if(isMtn(b.sprite)&&mtnFlip) mir^=1;
     sp.scale.x = mir ? -1 : 1; }
   document.getElementById('ori').textContent='mountains '+(mtnFlip?'flipped':'normal');
   fit(); }
 window.tg=()=>{ mtnFlip^=1; layout(); };
 document.getElementById('stat').textContent=items.length+' buildings &middot; '+names.length+' types';
 let drag=false,px,py;
 app.view.addEventListener('mousedown',e=>{drag=true;px=e.clientX;py=e.clientY;});
 window.addEventListener('mouseup',()=>drag=false);
 window.addEventListener('mousemove',e=>{if(!drag)return;world.x+=e.clientX-px;world.y+=e.clientY-py;px=e.clientX;py=e.clientY;});
 app.view.addEventListener('wheel',e=>{e.preventDefault();const f=e.deltaY<0?1.12:0.893;
   const r=app.view.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
   const wx=(mx-world.x)/world.scale.x,wy=(my-world.y)/world.scale.y;
   world.scale.x*=f;world.scale.y*=f;world.x=mx-wx*world.scale.x;world.y=my-wy*world.scale.y;},{passive:false});
 window.addEventListener('keydown',e=>{ if(e.key==='f')tg(); });
 window.zoom=f=>{world.scale.x*=f;world.scale.y*=f;};
 window.fit=()=>{const b=world.getLocalBounds(); if(!b.width)return;
   const s=Math.min(app.renderer.width/(b.width+200),app.renderer.height/(b.height+200));
   world.scale.set(s); world.x=app.renderer.width/2-(b.x+b.width/2)*s; world.y=app.renderer.height/2-(b.y+b.height/2)*s;};
 layout();
})();
</script></body></html>"""


def register_admin(server):
    app = server.app
    # restore persisted donut balance (used by the patched protocurrency handler)
    server.donut_balance = _read_donuts()

    def admin():
        main = sys.modules.get('__main__')
        play_modes = list(getattr(main, 'tsto_events', {}).items())
        host = request.host
        return render_template_string(
            PAGE,
            host=host,
            active=getattr(server, 'town_filename', '') or '(none)',
            donuts=getattr(server, 'donut_balance', DEFAULT_DONUTS),
            towns=_town_rows(server.towns_dir),
            play_modes=play_modes,
            current_play_mode=getattr(server, 'current_play_mode', 0),
        )

    def admin_donuts():
        try:
            v = max(0, int(request.form.get('donuts', DEFAULT_DONUTS)))
        except Exception:
            v = DEFAULT_DONUTS
        server.donut_balance = v
        try:
            open(DONUT_FILE, 'w').write(str(v))
        except Exception:
            pass
        return redirect('/admin')

    def admin_active_town():
        town = (request.form.get('town') or '').strip()
        # only allow existing town files (no path traversal)
        if town and town in os.listdir(server.towns_dir) and not town.startswith('.'):
            server.town_filename = town
            try:
                server.load_town()
            except Exception:
                pass
            _set_config_active_town(town)
        return redirect('/admin')

    def admin_playmode():
        try:
            server.set_game_mode(int(request.form.get('playmode', 0)))
        except Exception:
            pass
        return redirect('/admin')

    def admin_edit_town():
        town = (request.form.get('town') or '').strip()
        if not town or town.startswith('.') or town not in os.listdir(server.towns_dir):
            return redirect('/admin')
        path = os.path.join(server.towns_dir, town)
        try:
            land = LandData_pb2.LandMessage()
            land.ParseFromString(open(path, 'rb').read())
            money = (request.form.get('money') or '').strip()
            level = (request.form.get('level') or '').strip()
            if money != '':
                land.userData.money = max(0, int(money))
            if level != '':
                lv = max(1, int(level))
                land.userData.level = lv
                land.userData.visualLevel = lv
            with open(path, 'wb') as f:
                f.write(land.SerializeToString())
            # if the active town was edited, refresh in-memory copy so the next
            # client fetch serves the new values
            if town == getattr(server, 'town_filename', None):
                server.load_town()
        except Exception as e:
            server.log_error(f"[admin] edit-town failed: {e}")
        return redirect('/admin')

    def admin_map():
        town = (request.args.get('town') or getattr(server, 'town_filename', '') or '').strip()
        if not town or town.startswith('.') or town not in os.listdir(server.towns_dir):
            return redirect('/admin')
        try:
            vb, nb, nc, body = _town_map(server.towns_dir, town)
        except Exception as e:
            server.log_error(f"[admin] map failed: {e}")
            return redirect('/admin')
        return render_template_string(MAP_PAGE, town=town, vb=vb, nb=nb, nc=nc, body=body)

    app.add_url_rule('/admin', view_func=admin)
    app.add_url_rule('/admin/donuts', methods=['POST'], view_func=admin_donuts)
    app.add_url_rule('/admin/active-town', methods=['POST'], view_func=admin_active_town)
    app.add_url_rule('/admin/playmode', methods=['POST'], view_func=admin_playmode)
    def townview():
        return Response(TOWNVIEW_HTML, mimetype="text/html")

    def townview_json():
        return send_from_directory(TOWNVIEW_DIR, "town.json")

    def townview_sprite(fn):
        return send_from_directory(os.path.join(TOWNVIEW_DIR, "sprites"), fn)

    app.add_url_rule('/admin/edit-town', methods=['POST'], view_func=admin_edit_town)
    app.add_url_rule('/admin/map', view_func=admin_map)
    app.add_url_rule('/admin/townview', view_func=townview)
    app.add_url_rule('/admin/townview/town.json', view_func=townview_json)
    app.add_url_rule('/admin/townview/sprites/<path:fn>', view_func=townview_sprite)
    server.log_debug('[admin] /admin panel registered')
