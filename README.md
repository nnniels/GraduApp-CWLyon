# GraduApp

Mobile treasure-hunt web app. Flask + Jinja + HTMX + SQLite, exposed through a Cloudflare Tunnel.
See [Docs/architecture.md](Docs/architecture.md).

## Layering

`web -> db -> engine`. The `engine` package is pure Python: no Flask, no SQL.

## Setup
At repo root :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

## Run (dev)
After having copied `.env`, edit 
- `SECRET_KEY`
- `ADMIN_PASSWORD`

Then 

```powershell
flask seed
```

```powershell
flask --app graduapp run --debug
```

Then, if no error are thrown, open `http://127.0.0.1:5000` in web browser.

Passwords are in `./content/teams` and `./content/steps`.

## Run (Linux, production-like)

Full install from `git clone`: [Docs/install_linux.md](Docs/install_linux.md). Commands below run from the repo root with the venv active (`. .venv/bin/activate`) and `.env` loaded (`set -a; . ./.env; set +a`).

### 1. App by hand (gunicorn)

```bash
gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8000 wsgi:app
```

Keep `--workers 1` (in-memory rate limits). Check: `curl -I http://127.0.0.1:8000/`. Use `tmux` so it survives a closed SSH session.

### 2. Tunnel by hand

```bash
cloudflared tunnel run graduapp
```

Needs `~/.cloudflared/config.yml`. The app must already listen on 127.0.0.1:8000.

### 3. As services (systemd)

Units: `graduapp` (gunicorn) and `cloudflared` (tunnel).

| Action | Command |
|---|---|
| Status | `systemctl status graduapp cloudflared` |
| Start / stop | `sudo systemctl start graduapp` / `sudo systemctl stop graduapp` |
| Restart (after editing `.env` or code) | `sudo systemctl restart graduapp` |
| Start at boot: enable / disable | `sudo systemctl enable graduapp` / `sudo systemctl disable graduapp` |
| Enable and start now | `sudo systemctl enable --now graduapp` |
| Disable and stop now | `sudo systemctl disable --now graduapp` |
| Logs (follow) | `journalctl -u graduapp -f` |
| After editing the unit file | `sudo systemctl daemon-reload` then restart |

Same commands for `cloudflared`. To go back to manual mode, `disable --now` both services, then use sections 1 and 2.

Do not run the manual gunicorn while the service is running: both want port 8000.

Reset the game while serving (as your own user, `.env` loaded): `flask --app graduapp reset-game`. No restart needed.

## Organiser view

Open `/admin` (or the discreet gear under the team list on screen A) and log in with `ADMIN_PASSWORD`. Empty or `change-me` disables the view (404). The session lasts 8 hours; use the Log out button.

| Tab | Content |
|---|---|
| Teams | Phase, step, next code, score, wrong codes, last event. Click a team for what it typed. Sets or removes the general-challenges deadline (entered in `DISPLAY_TZ`). |
| Log | Events newest first, filter by team, "Older events" paging |
| Codes | Validation codes per itinerary, plus join codes |

CSV (comma separated, UTF-8 with BOM): `/admin/events.csv` and `/admin/answers.csv`. Pages are read-only and refreshed by reloading. After pulling this version, run `pip install -e ".[prod]"` again (new dependency `tzdata`).

## Log


```powershell
flask show-events --team team-1 --tail 50
```

## Reset

Back to the pre-game state: all teams `NOT_STARTED`, ticks and event log erased. Content, teams, join codes and the general-challenges deadline are kept.

```powershell
flask reset-game            # asks for confirmation
flask reset-game --names    # also restores team names from content/teams.yaml
flask reset-game --yes      # no prompt
```

State lives in one SQLite file, `instance/graduapp.sqlite` (team names included, in `team.name`).

## Test

```powershell
pytest
```
