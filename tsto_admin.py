"""TSTO admin panel -- added to the d-fens server in-process via register_admin(server).

Not part of upstream d-fens. Patches tsto_server.py to (a) read the donut
balance from server.donut_balance and (b) call register_admin(self) once routes
are set up.

Provides /admin: editable donut balance, a towns overview (level / cash /
building & character counts / last-saved), switch-active-town, a cash/level
editor, and the play-mode selector. Town stats are read from the save
protobufs. Reachable on the same port as the game server.

The isometric town viewer that used to live here is gone. This server exists to
be a loopback sidecar for a desktop client that draws Springfield itself; a
second renderer, fed by a sprite-extraction pipeline over the game's own art,
was a good answer to a question nobody is asking any more.
"""
import os
import re
import sys
import time

from flask import request, redirect, render_template_string

from proto import LandData_pb2

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
<p class="sub">{{host}} · active town: <b>{{active}}</b></p>

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


def _set_config_active_town(town):
    """Persist active_town into config.json (text sub to preserve formatting)."""
    try:
        s = open(CONFIG_FILE).read()
        s2 = re.sub(r'("active_town"\s*:\s*")[^"]*(")', r'\g<1>' + town + r'\2', s, count=1)
        if s2 != s:
            open(CONFIG_FILE, 'w').write(s2)
    except Exception:
        pass


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


    app.add_url_rule('/admin', view_func=admin)
    app.add_url_rule('/admin/donuts', methods=['POST'], view_func=admin_donuts)
    app.add_url_rule('/admin/active-town', methods=['POST'], view_func=admin_active_town)
    app.add_url_rule('/admin/playmode', methods=['POST'], view_func=admin_playmode)
    app.add_url_rule('/admin/edit-town', methods=['POST'], view_func=admin_edit_town)
    server.log_debug('[admin] /admin panel registered')
