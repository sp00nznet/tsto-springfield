# TSTO Springfield — sp00nz fork

A private, self-hosted server for **The Simpsons: Tapped Out**, forked from
[`d-fens/tsto_server`](https://github.com/d-fens/tsto_server). EA shut the official
servers down in Jan 2025; this keeps a personal Springfield playable — Tailscale-only,
no public exposure, all currencies free.

This fork keeps the upstream protocol/server intact and adds **bug fixes**, **quality-of-life
config**, and a **web admin panel with an isometric town viewer** rendered from your save +
the real game art.

> Credit: all of the core game-server protocol work is upstream `d-fens/tsto_server`
> (Flask + protobuf). This fork is changes on top of it. Upstream's original setup docs are
> preserved at the bottom of this file.

---

## What's different vs upstream

### Bug fixes
| Fix | Why it matters |
|-----|----------------|
| **`deleteToken` route added** | Upstream has no handler, so a *returning* client (already holding a whole-land edit token) loops `checkToken → protoWholeLandToken → deleteToken(404)` on boot and never downloads the town — **endless spinning donut**. Returns empty 200 to ack the lock release. |
| **`config.json` `dlc_dir` → `"dlc"`** | Upstream ships `dlc_dir: "gameassets"` while the compose file mounts the DLC at `/app/dlc/`, so the server 404s every asset and the game shows **"cannot connect to server"** after booting. Aligned to the mount. |
| **Crash-guard in `load_friends_data`** (`except google.protobuf.message.DecodeError` → `except Exception`) | Upstream references an unimported name, so **any** unparseable file in `towns/` crashes startup with `NameError`. Bad files are now skipped. |
| **`restart: unless-stopped`** (override) | Upstream sets no restart policy → containers **don't come back after a host reboot**. |
| **`towns/` bind-mounted** (override) | Upstream doesn't persist `towns/` → saves live in the container layer and are **wiped on every `--force-recreate`**. Now on the host. |

### Quality-of-life
- **Configurable donut balance** — upstream hardcodes `vcBalance = 1234567`; the server reads
  `server.donut_balance`, set live from the admin panel and persisted to `towns/.donut_balance`.
- **Default active town** — pin the town loaded on cold/anon boot (`config.json` `active_town`).

### New: web admin panel (`/admin`)
- **Donut editor** — set the balance from a form; effective on the next currency fetch.
- **Towns overview** — every town parsed from its save: level, cash, building & character counts,
  last-saved, size; switch the active town live.
- **Cash/level editor** — edit a town's `userData.money` / `level` by rewriting the save protobuf.
- **Play-mode / event selector** (the only thing upstream's `/dashboard` did).

### New: town map + isometric viewer
- **`/admin/map`** — schematic top-down SVG of building/character positions (pan/zoom), from the save.
- **`/admin/townview`** — **interactive isometric WebGL viewer** (PixiJS) of your actual town,
  rendered from the save + the **real DLC sprite art**. Drag to pan, wheel to zoom — see/scroll your
  Springfield on a big screen instead of a phone.

### New: render pipeline (`tools/render/`)
Builds the town-viewer assets from your save + the DLC you've mirrored:
1. `tsto_render_index.py` — cache an rgb sprite-locator index over the DLC.
2. `tsto_render_resolve.py` — map building ids → sprites via `inventory_*.xml`, `*_buildings.xml`,
   and `*_buildingsassetdata.xml` (BSv2).
3. `tsto_render_extract.py` / `tsto_render_overrides.py` — extract sprites with
   [`tstorgb`](https://github.com/al1sant0s/tstorgb) (`--first`, single-sprite, load-checked).
4. `tsto_render_refresh.py` — re-read the current save and rebuild `townview/town.json` end-to-end.

> These are **Proxmox/LXC deployment scripts** — they SSH to the PVE host and drive the container.
> Set `PVE_HOST` and `PVE_PASS` env vars (and adjust the container VMID / DLC path) to adapt.
> The DLC art is **not** included.

---

## How it runs (our setup)
- **Docker-in-LXC** on Proxmox, **Tailscale-only** (no public domain, no TLS — the game speaks plain
  HTTP, so a Tailscale `100.x` IP is all the patched client needs).
- Android client is a **clean EA 4.69.x APK** re-pointed at the server with `tstoapkpatcher` (it
  matches EA's original URLs and patches `libscorpio.so` by hash+offset, so it only works on a
  *clean* APK — not an already-patched one).
- DLC mirrored from EA's still-live CDN via `tstomirror`, served at `/gameassets/`.

## Known gaps (viewer fidelity)
- **House skins not applied** — TSTO recolors one base house sprite (`generichouse00`, pink) per
  building via a `skin` field; the viewer shows the base color (so "Brown House" renders pink).
- **Approximate pivots** — bottom-center anchoring instead of each sprite's true pivot, so tightly
  packed sprites can occlude each other.
- **Sprite facing** — sprites are pre-drawn for one camera angle; orientation is calibrated per town
  (`/admin/townview` has a "flip mountains" toggle).
- The viewer reflects the **server-saved** town — newly placed buildings appear only after the game
  syncs a save and `tsto_render_refresh.py` is re-run.

## Layout
```
tsto_server.py              upstream server + our patches
tsto_admin.py               /admin panel + /admin/map + /admin/townview  (NEW)
config.json                 dlc_dir fix + active_town
docker-compose.override.yml mounts, towns persistence, restart policy     (NEW)
tools/render/               town-viewer build pipeline                    (NEW)
townview/                   generated viewer assets (gitignored)
```

---
---

# Upstream documentation (d-fens/tsto_server)

> The original upstream README follows, unmodified, for setup reference.

This is a work-in-progress (WIP) release of a local server that allows you to play your Springfield in the "The Simpsons: Tapped Out" mobile app.

## How to Setup and Use (Docker)

Before you run this program, you will need a few things:

[Docker](https://www.docker.com/get-started/) needs to be setup and operational.

1) Optional: A copy of your existing world (see [teamtsto.org](https://teamtsto.org/) for making a backup of your town) or a backup of your friends' town (see [tsto_friend_puller](https://github.com/tjac/tsto_friend_puller)). Save the file to the "towns" directory WITHOUT any file extension.
2) Create a folder called `tsto`
3) Download [docker-compose.yml](https://raw.githubusercontent.com/d-fens/tsto_server/refs/heads/master/docker-compose.yml), [config.json](https://raw.githubusercontent.com/d-fens/tsto_server/refs/heads/master/config.json) and [.env](https://raw.githubusercontent.com/d-fens/tsto_server/refs/heads/master/.env) to the `tsto` folder.
4) Download a copy of the APK of the [The Simpsons: Tapped Out game](https://apkpure.com/the-simpsons%E2%84%A2-tapped-out/com.ea.game.simpsons4_row) and place within the `tsto` folder. Make sure it is named 'Tapped Out.apk'
5) Edit the `.env` file and replace the APK name with the name; and the IP address with your machines IP.
6) Run `docker-compose up -d` from a command prompt in the `tsto` folder.
7) Install the APK on an Android phone or tablet. Optionally, you can play the game on your PC by using [BlueStacks](https://www.bluestacks.com/download.html) or equivalent emulator.
8) Optional: Run `docker compose logs -f` to see issues with containers.

## How to play

The system currently leverages the login AND anonymous play system to allow users to select different worlds to play. By default, clicking the "Tap to play anonymously" will load the "mytown" world. If the user wants to play a different town, they should click the EA Login button, then enter an email address that has the username equal to the town's filename in the towns directory. For example, if you want to load a town with the filename "mysupertown" then you would enter "mysupertown@a.a". The @ and . are required by the TSTO application, so any random domain will work. On the next screen, after pressing the "Log In" button, enter any 5 digit code and press "Verify".

## Running old events

You can run past The Simpsons: Tapped Out events. Navigate to `http://x.x.x.x/dashboard` for a simple dashboard that lets you trigger old events/quest lines. This works by tricking the app into thinking the current date is in the past (the start of the selected event).

## Credits / lineage
* Upstream server: [d-fens/tsto_server](https://github.com/d-fens/tsto_server) (built on [tjac/tsto_server](https://github.com/tjac/tsto_server))
* Asset conversion: [al1sant0s/tstorgb](https://github.com/al1sant0s/tstorgb)
