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
