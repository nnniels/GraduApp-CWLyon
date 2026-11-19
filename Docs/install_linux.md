# Install on the Linux laptop

From `git clone` to a service that survives reboots. Replace `<you>` with your Linux user and `game.example.com` with your domain.

Layers, bottom to top: **app (gunicorn, 127.0.0.1:8000) → tunnel (cloudflared) → Cloudflare → phones**. No inbound port is opened on the laptop.

## 1. Get the code

```bash
git clone <repo-url> ~/GraduApp-CWLyon
cd ~/GraduApp-CWLyon
```

## 2. Python environment

```bash
sudo apt install python3 python3-venv     # do NOT apt-install gunicorn
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[prod]"                  # app + gunicorn, inside the venv
which gunicorn                            # must be .../GraduApp-CWLyon/.venv/bin/gunicorn
```

Why: the system gunicorn uses the system Python, which has no Flask. If bash still calls an old path, run `hash -r`.

## 3. Configuration

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
nano .env
chmod 600 .env
```

Set in `.env`:

| Key | Value |
|---|---|
| `SECRET_KEY` | the generated string (the app refuses to start with empty or `change-me`) |
| `COOKIE_SECURE` | `1` (the tunnel serves HTTPS) |
| `ADMIN_PASSWORD` | a non-empty password |

Systemd reads `.env` as plain `KEY=value` lines: no quotes, no `export`.

## 4. Seed the database

```bash
set -a; . ./.env; set +a                  # load .env into this shell
flask --app graduapp seed
```

Creates `instance/graduapp.sqlite` from the YAML in `content/`.

## 5. Test the app alone (stage 1)

```bash
gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8000 wsgi:app
curl -I http://127.0.0.1:8000/            # expect 200
```

Keep `--workers 1`: rate-limit counters live in memory, and more workers would multiply the limits. Stop with Ctrl+C.

## 6. Cloudflare Tunnel

Prerequisite: a domain managed by Cloudflare (DNS zone active).

```bash
# install cloudflared: follow https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel login                              # opens a browser, pick the domain
cloudflared tunnel create graduapp                    # prints <TUNNEL_ID>, writes ~/.cloudflared/<TUNNEL_ID>.json
cloudflared tunnel route dns graduapp game.example.com
nano ~/.cloudflared/config.yml
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/<you>/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: game.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

What each part does:
- `create` makes the tunnel and its secret credentials file (keep it private).
- `route dns` creates the CNAME `game.example.com → <TUNNEL_ID>.cfargotunnel.com`.
- `ingress` maps the hostname to the local app; the last rule rejects anything else.

## 7. Test the tunnel (stage 2)

Terminal 1: gunicorn (step 5). Terminal 2:

```bash
cloudflared tunnel run graduapp
```

On a phone with wifi off, open `https://game.example.com`. Pick a team, enter its join code, reach screen B. Check on the laptop:

```bash
flask --app graduapp show-events --tail 20
```

Stop both with Ctrl+C.

## 8. App service (stage 3)

```bash
sudo nano /etc/systemd/system/graduapp.service
```

```ini
[Unit]
Description=GraduApp (gunicorn)
After=network.target

[Service]
User=<you>
WorkingDirectory=/home/<you>/GraduApp-CWLyon
EnvironmentFile=/home/<you>/GraduApp-CWLyon/.env
ExecStart=/home/<you>/GraduApp-CWLyon/.venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8000 wsgi:app
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

| Line | Purpose |
|---|---|
| `User` | not root: the venv and SQLite file stay yours |
| `WorkingDirectory` | relative paths in `.env` (`instance/`, `content`) resolve from here |
| `EnvironmentFile` | loads the secrets |
| `ExecStart` | full path to the venv's gunicorn |
| `Restart`, `RestartSec` | comes back 3 s after a crash |
| `NoNewPrivileges` | cheap hardening |

Start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now graduapp
systemctl status graduapp
curl -I http://127.0.0.1:8000/
```

## 9. Tunnel service

systemd runs as root, so give it its own copy of the config:

```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/config.yml ~/.cloudflared/<TUNNEL_ID>.json /etc/cloudflared/
sudo sed -i 's#/home/<you>/.cloudflared#/etc/cloudflared#' /etc/cloudflared/config.yml
sudo cloudflared service install
sudo systemctl enable --now cloudflared
systemctl status cloudflared
```

## 10. Reboot test

```bash
sudo reboot
```

Without touching the laptop, open the site from a phone on 4G. If it loads, the install is done.

For the event, disable suspend (and lid-close suspend: `HandleLidSwitch=ignore` in `/etc/systemd/logind.conf`).

## Troubleshooting

| Symptom | Cause |
|---|---|
| `No module named flask` | wrong gunicorn (system one); use the venv path |
| `No such file /usr/bin/gunicorn` | bash cache: `hash -r` |
| App refuses to start | `SECRET_KEY` empty or `change-me`; `.env` unreadable by `<you>` |
| `203/EXEC` | wrong `ExecStart` path |
| `200/CHDIR` | wrong `WorkingDirectory` |
| Cloudflare 1033 / 502 | gunicorn or cloudflared not running, or wrong port in `ingress` |
| Cookie lost / cannot join | `COOKIE_SECURE=1` while testing over plain HTTP |
| Tunnel cannot connect | outbound port 7844 blocked; add `--protocol http2` |

Logs: `journalctl -u graduapp -e`, `journalctl -u cloudflared -e`.
