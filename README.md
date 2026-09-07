# tsto-springfield

A self-hosted server for **The Simpsons: Tapped Out**, forked from
[`d-fens/tsto_server`](https://github.com/d-fens/tsto_server). EA shut the
official servers down in January 2025; this keeps a personal Springfield
playable.

Its job here is to be a **loopback sidecar**. The game speaks plain HTTP to a
configurable base URL, so
[tstorecomp](https://github.com/sp00nznet/tstorecomp) -- *Tapped Out* recompiled
to a native desktop application -- starts this on `127.0.0.1` at launch and
shuts it down on exit. Nothing leaves the machine. It runs standalone against an
Android client too, which is what it was built for.

> Credit: all of the core game-server protocol work is upstream
> `d-fens/tsto_server` (Flask + protobuf). This fork is changes on top of it.
> Upstream's original setup docs are preserved at the bottom of this file.

## Licence

**None, and that is not an oversight.** Upstream `d-fens/tsto_server` states no
licence at all, so it is "all rights reserved" by default and neither it nor
this fork can be relicensed by us. That is why tstorecomp reaches this over a
socket as a separate process and vendors it as a submodule: a submodule
references code without redistributing it, and a separate process is not a
derivative work. Do not copy this into an MIT project.

No EA code or content is in this repository. *The Simpsons: Tapped Out* is
(c) Electronic Arts; this project is not affiliated with or endorsed by EA,
Bight Games, or Fox.

---

## What's different vs upstream

### Bug fixes
| Fix | Why it matters |
|-----|----------------|
| **`deleteToken` route added** | Upstream has no handler, so a *returning* client (already holding a whole-land edit token) loops `checkToken -> protoWholeLandToken -> deleteToken(404)` on boot and never downloads the town -- **endless spinning donut**. Returns empty 200 to ack the lock release. |
| **`config.json` `dlc_dir` -> `"dlc"`** | Upstream ships `dlc_dir: "gameassets"` while the compose file mounts the DLC at `/app/dlc/`, so the server 404s every asset and the game shows **"cannot connect to server"** after booting. Aligned to the mount. |
| **Crash-guard in `load_friends_data`** (`except google.protobuf.message.DecodeError` -> `except Exception`) | Upstream references an unimported name, so **any** unparseable file in `towns/` crashes startup with `NameError`. Bad files are now skipped. |
| **`restart: unless-stopped`** (override) | Upstream sets no restart policy, so containers do not come back after a host reboot. |
| **`towns/` bind-mounted** (override) | Upstream does not persist `towns/`, so saves live in the container layer and are wiped on every `--force-recreate`. Now on the host. |

### Quality-of-life
- **Configurable donut balance** -- upstream hardcodes `vcBalance = 1234567`;
  the server reads `server.donut_balance`, set live from the admin panel and
  persisted to `towns/.donut_balance`.
- **Default active town** -- pin the town loaded on cold/anon boot
  (`config.json` `active_town`).

### Admin panel (`/admin`)
Configuration for the sidecar, on the same port as the game server.

- **Donut editor** -- set the balance from a form; effective on the next
  currency fetch.
- **Towns overview** -- every town parsed from its save: level, cash, building
  and character counts, last-saved, size; switch the active town live.
- **Cash/level editor** -- edit a town's `userData.money` / `level` by rewriting
  the save protobuf.
- **Play-mode / event selector** -- the only thing upstream's `/dashboard` did.

### Removed: the isometric town viewer
This fork used to serve an interactive WebGL view of your town, rendered from
the save plus extracted DLC sprite art, with a five-stage pipeline under
`tools/render/` to build its assets. It is gone. The client this now feeds draws
Springfield itself, at the frame rate the engine draws it at, from the same art;
a second renderer with approximate pivots and unapplied house skins was a good
answer to a question nobody is asking any more.

## Running it

```sh
cp .env.example .env        # fill in the URLs your client will use
docker compose up -d
```

Point the client at the server's base URL. On Android that has to be patched
into `libscorpio.so` by hash and offset; in a native build it is a config value.

Put a town save in `towns/` with no file extension. `mytown` is the one anonymous
play loads by default; `config.json`'s `active_town` changes that.

## Layout
```
tsto_server.py               upstream server + our patches
tsto_admin.py                /admin panel                              (new)
auth_manager.py              upstream
config.json                  dlc_dir fix + active_town
docker-compose.override.yml  mounts, towns persistence, restart policy (new)
proto/                       upstream generated protobuf
towns/                       save files -- yours, not committed
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
