# GraduApp

Mobile treasure-hunt web app. Flask + Jinja + HTMX + SQLite, exposed through a Cloudflare Tunnel.
See [Docs/architecture.md](Docs/architecture.md).

## Layering

`web -> db -> engine`. The `engine` package is pure Python: no Flask, no SQL.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

## Run (dev)

```powershell
flask --app graduapp run --debug
```

## Test

```powershell
pytest
```
