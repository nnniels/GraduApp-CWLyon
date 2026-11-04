# Step 9: exposure and hardening (Cloudflare)

Status: **analysis only, nothing implemented yet.**

Facts marked **[verified]** were checked in the Cloudflare documentation today. Facts marked **[verify]** come from memory and must be confirmed in the dashboard.

## 1. Goal and expected outcome

Make the app reachable from phones on 4G through a stable HTTPS address, without exposing the host, and without giving a stranger or a bot anything useful.

| Outcome | Meaning |
|---|---|
| Stable public URL | A named tunnel on a domain we control. The URL can be printed on QR codes. |
| Host not exposed | No inbound port is open. The app listens on `127.0.0.1` only. The tunnel connects outbound. |
| `/admin` closed to strangers | Cloudflare Access in front, the app password behind it. |
| Abuse is slowed down | Wrong codes are rate-limited in the app, and floods are absorbed at the edge. |
| Nothing sensitive reaches a phone | Validation codes, join codes and other teams' data never appear in a player response. |
| Survives a crash | Both processes restart by themselves and start in the right order. |

## 2. Starting point: what the code does today

Checked in the repository.

| Area | Finding | Consequence |
|---|---|---|
| Deploy files | `deploy/graduapp.service`, `cloudflared.service` and `cloudflared.example.yml` exist as untested templates. | Neither unit has a `User=`, so both run as root. `cloudflared` does not wait for the app. The tunnel file assumes a locally managed tunnel with a credentials file. |
| Dependencies | `gunicorn` is only in the optional `prod` extra. | The server install must use `pip install -e ".[prod]"`. |
| Rate limit | Flask-Limiter has no default limit. Only `POST /join` is limited, per team, counting wrong codes only. | The step validation code (`POST /game/arrive`) is **not limited**. |
| Rate-limit key | Default key is `get_remote_address`. Behind the tunnel it is always `127.0.0.1`. | A per-IP limit would punish everybody at once. The organiser login (step 8) needs a real client IP. |
| 429 page | The handler for 429 renders screen A. | On a game route called by HTMX, it would swap screen A into the game panel. |
| Real client IP | No `CF-Connecting-IP` handling, no `ProxyFix`. | Logs and limits cannot tell clients apart. |
| Response headers | None added: no CSP, no `nosniff`, no `Referrer-Policy`, no `Cache-Control: no-store`. | Defaults only. |
| Inline JavaScript | Templates use inline `onclick`, and HTMX injects an inline `<style>`. | A strict CSP needs a small refactor first. |
| CSRF | No token. `SameSite=Lax` only. | Acceptable for this audience. Revisit if cheap. |
| Cookie | `Secure` flag is opt-in (`COOKIE_SECURE=1`). | Must be on in production. |
| Debug | `flask run --debug` exposes the Werkzeug debugger. | Must never run on the server. Nothing prevents it today. |
| Health check | No `/healthz` route. | No cheap way to test the tunnel, systemd or an uptime monitor. |
| Admin | Not built. `ADMIN_PASSWORD` defaults to `""`. | Fail-closed handling is part of step 8. |
| Leak guarantees | Already tested: no validation code in any player response, the join list has no codes, `StepContent` has no code field, media needs a team login. | Good base. They need extending to the new routes. |

## 3. Work packages

### A. Cloudflare account, domain and tunnel (manual, by you)
1. Cloudflare account.
2. A domain on Cloudflare. **Start first: a nameserver change can take hours.**
3. A named tunnel, with a public hostname such as `game.<domain>` pointing to `http://127.0.0.1:8000`.
4. The tunnel token or credentials stored on the host with mode `600`.

### B. The host (systemd, firewall)
1. A dedicated unprivileged user for both services.
2. `graduapp.service`: gunicorn on `127.0.0.1:8000`, one worker with threads, `Restart=always`, `EnvironmentFile` mode `600`, write access only to `instance/`.
3. `cloudflared.service`: `After=` and `Wants=` the app, `Restart=always` with a short delay, token from an environment file.
4. Firewall: no inbound port open. Check that only loopback listens (`ss -ltnp`).
5. Server clock kept in sync (NTP). The timer authority is the server clock.
6. gunicorn access log in the journal, showing the real client IP from `CF-Connecting-IP`.

### C. Cloudflare Access
1. A self-hosted Access application on the game hostname.
2. Covers `/admin` **and** `/admin/*`. **[verified]** A wildcard path does not cover the parent path, so one rule alone leaves a hole.
3. One policy: allow the organiser emails, using one-time PIN by email. Long session duration.
4. Players' routes stay outside Access. No friction for phones.

### D. Application changes
| # | Change | Where |
|---|---|---|
| D1 | `client_ip()` helper: use `CF-Connecting-IP` **only** when the request comes from loopback, otherwise the remote address. Used as the default limiter key and for logs. | `web/auth.py` |
| D2 | Limit wrong validation codes on `POST /game/arrive`: per team, only wrong codes count. | `web/game.py` |
| D3 | A 429 handler that answers HTMX requests with a small popup and plain requests with a page. | `web/` |
| D4 | After-request headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options` or CSP `frame-ancestors`, `Cache-Control: no-store` on game and admin responses, `X-Robots-Tag: noindex`. | `web/` |
| D5 | CSP (see choice 8). Needs the inline handlers moved into the JS file. | templates, `static/js` |
| D6 | `/healthz` returning 200, without touching secrets. | `web/` |
| D7 | `robots.txt` disallowing everything. | `web/` |
| D8 | Production guards: refuse to start with debug on or a weak `SECRET_KEY` when `COOKIE_SECURE=1`. | `__init__.py` |
| D9 | Static files with a short cache lifetime, so CSS and JS edits show up. | config |

### E. Leak audit
- Extend the existing "no code reaches a phone" test to the new routes: screen C, 429 popups, `/healthz`, error pages.
- Error pages are generic, with no traceback and no server version.
- Admin routes return nothing to an anonymous request, including CSV routes (checked together with step 8).
- The cookie holds only `team_id` and the selected view. Never a code or a name.
- The Flask cookie is signed, not encrypted: it must never carry a secret.

### F. Verification
Automated (pytest): D1 to D9, the 429 handling, the leak tests.
Manual, from a phone **on 4G**, never the LAN:

| Check | Expected |
|---|---|
| Open the public URL | Screen A over HTTPS, `Secure` cookie set |
| Open `/admin` while logged out | Cloudflare Access login, not the app |
| Open `/admin/anything` | Same |
| `curl` the public IP of the host | Nothing answers |
| 11 wrong join codes, then 11 wrong validation codes | A 429 message, no broken screen |
| Kill `gunicorn`, then `cloudflared` | Both come back, the game resumes |
| Reboot the host | Both start in order |

## 4. Impact

| Area | Impact |
|---|---|
| Existing code | Small and local: one helper, one limit, one handler, one after-request hook, the guards, and moving inline `onclick` to the JS file. No engine or database change. |
| Existing tests | The 170 tests keep running. Tests add the `CF-Connecting-IP` cases (trusted only from loopback). Rate-limit state is reset per test as today. |
| Organiser view (step 8) | Shares `client_ip()` and the limiter key, so build D1 first. The Access rule can exist before the routes do. |
| Operations | Two systemd services and two environment files to manage. A new failure mode: the tunnel or the DNS. |
| Cost | A domain, about the price of a year of registration **[verify]**. Cloudflare Zero Trust is free for a small number of users **[verify]**. |
| Timeline | The only slow item is DNS propagation. Everything else can be built and tested locally first. |

## 5. Expected outcomes (acceptance criteria)
1. A phone on 4G plays a whole game through the public URL.
2. `/admin` and `/admin/*` cannot be reached without passing Access, and the app still asks for its own password.
3. No inbound port is open on the host, and the app listens on loopback only.
4. A burst of wrong validation codes ends in a clear 429 message. The page is not broken.
5. A burst of wrong join codes is limited per team, as today.
6. No response to a player contains a validation code, a join code, another team's data, or a stack trace.
7. Killing either service, or rebooting the host, restores the game without manual steps.
8. A stranger scanning the hostname finds only screen A.

## 6. Choices to make

### 1. Tunnel management
| Option | Pros | Cons |
|---|---|---|
| **Remotely managed (token, set up in the dashboard)** | One token in an environment file. No credentials file, no `cert.pem`. Ingress editable without touching the host. Recommended by Cloudflare. | Ingress lives in the dashboard, not in git. |
| Locally managed (`config.yml` and credentials file, as in `deploy/`) | Everything in git. | More files on the host, and a one-time `cloudflared login`. |

**Pick:** remotely managed. I would replace `cloudflared.example.yml` with a short note and keep the unit.

### 2. Domain
| Option | Notes |
|---|---|
| **Register a cheap domain with Cloudflare** | No nameserver wait, simplest. |
| Move a domain you own | Works, but the nameserver change can take hours. |
| A quick tunnel (`trycloudflare.com`) | Random URL, **no Access possible**. Useful only for a first smoke test. |

### 3. Access: path or hostname
| Option | Pros | Cons |
|---|---|---|
| **Path rules `/admin` and `/admin/*`** | One hostname, matches the plan in `prompt07`. | Two rules needed, easy to forget one. |
| Separate hostname for admin | Cleaner Access rule. Cookies are isolated per host. | The app still answers `/admin` on the player hostname unless it checks the `Host` header, so Access could be bypassed there. |

**Pick:** path rules, both paths, and a test that checks each.

### 4. Access identity
| Option | Notes |
|---|---|
| **One-time PIN by email, allow-list** | No identity provider to set up. Fine for 1 to 3 organisers. |
| Google or GitHub login | Nicer, more setup. |

### 5. Should the app verify the Access JWT?
| Option | Notes |
|---|---|
| **No: Access, plus the app password** | Simple. The origin is reachable only through the tunnel. |
| Yes: check `Cf-Access-Jwt-Assertion` | Closes the case of a misrouted hostname. Adds a dependency and configuration. |

**Pick:** no. The app password is already the second layer.

### 6. Client IP source
| Option | Notes |
|---|---|
| **`CF-Connecting-IP`, trusted only from loopback** | Documented header. Safe because the origin only listens on loopback. |
| `ProxyFix` on `X-Forwarded-For` | Works too, but the header can carry a chain. |

### 7. Limit on wrong validation codes
| Choice | Options | Pick |
|---|---|---|
| Key | per IP (wrong behind a venue network), **per team** | per team |
| Counts | all requests, **wrong codes only** | wrong codes only, through a flag set by the handler |
| Threshold | 5 per 5 min (strict), **10 per 5 min**, 20 per 10 min (lenient) | 10 per 5 min |

Players need a team cookie to reach this route, so the real risk is mashing and accidents, not attackers. The message must show how long to wait. A lockout in the middle of the game costs a team its time, so the window stays short. The `memory://` counters reset on restart: an accepted way for the organiser to unlock a team.

### 8. Content Security Policy
| Option | Pros | Cons |
|---|---|---|
| **Strict CSP after moving inline handlers into the JS file, and turning off HTMX's inline style** | Best protection against injected scripts. Player notes appear on the organiser's screen, so it matters. | A small refactor of about five handlers. |
| CSP allowing inline scripts | No refactor. | Protects little. |
| No CSP, other headers only | Nothing to change. | The weakest option. |

**Pick:** strict CSP. It must allow the OpenStreetMap iframe and Google Maps links.

### 9. Edge rate limiting
**[verified]** The free plan has **1 rule**, matching on the **path** only, counting by **IP**, over **10 seconds**, with a **10 second** block.

| Option | Notes |
|---|---|
| **One generous rule on `/join`, plus Bot Fight Mode** | Cheap flood guard. Cannot count wrong codes, so the app limit stays essential. |
| None | Fine for a small private event. |

Risk: several teams on the same venue Wi-Fi share one public IP, so keep the rule generous.

### 10. Process hardening
| Option | Notes |
|---|---|
| **Dedicated user, `NoNewPrivileges`, `ProtectSystem=strict`, write access only to `instance/`** | Cheap and effective. |
| Full sandbox, containers | Not worth it here. |

### 11. Counter storage
Keep `memory://` with a single worker. Raising the worker count would split the counters, so document it next to the service file.

## 7. Pitfalls

- **Access session expiry:** HTMX polling on admin pages gets redirected to Cloudflare's login, which fails silently across origins. Use a long session (24 h) and show a "session expired, reload" message.
- **Both Access paths:** `/admin` and `/admin/*`. **[verified]**
- **Outbound ports:** `cloudflared` needs outbound access to Cloudflare on port 7844. A restrictive network may block it. The fallback is `--protocol http2` **[verify]**.
- **Trust in the IP header:** it is only safe while the origin listens on loopback. Binding gunicorn to `0.0.0.0` would let anyone on the LAN forge it.
- **Edge caching:** Cloudflare caches static files by extension. Edits to CSS or JS can look stale during the rehearsal, so keep static cache lifetimes short.
- **Single point of failure:** one host, one tunnel. A second machine with the same image is the fallback (step 11).
- **Privacy:** access logs contain client IPs. Keep them short-lived and purge them after the event.
- **Secrets:** `.env` and the tunnel token mode `600`. Rotate the token and `ADMIN_PASSWORD` after the event. Rotating `SECRET_KEY` logs every phone out.
- **Debug:** never `--debug` on the server. A guard in D8 enforces it.
- **Free-plan changes:** Cloudflare plan limits change. Re-check the **[verify]** items in the dashboard.

## 8. Order of work

| Order | Task | Who | Needs Cloudflare? |
|---|---|---|---|
| 1 | Account and domain (A.1, A.2) | You | Yes, **start now** |
| 2 | D1 to D9 and tests (E) | Me | No |
| 3 | systemd units, firewall, hardening (B) | Me for the files, you for the host | No |
| 4 | Step 8: organiser view | Me | No |
| 5 | Tunnel and Access rules (A.3, A.4, C) | You, with my checklist | Yes |
| 6 | Verification from 4G (F) | You | Yes |

Steps 2 to 4 can be built and tested without Cloudflare, so the DNS wait costs no time.

## 9. Questions to answer

1. **Domain:** do you already own one, or should we register one with Cloudflare?
2. **Host:** which Linux machine runs the game (distribution, systemd available), and on which network? If it is on a restricted network, is outbound port 7844 allowed?
3. **Organiser emails** for the Access allow-list.
4. **Tunnel management:** remotely managed (my pick) or the locally managed files already in `deploy/`?
5. **CSP:** accept the small refactor for a strict policy (my pick)?
6. **Validation-code limit:** 10 wrong codes per 5 minutes per team, acceptable?
7. **Edge rate-limit rule and Bot Fight Mode:** enable, or skip?
