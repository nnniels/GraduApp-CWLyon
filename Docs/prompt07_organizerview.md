# Organiser view (step 8): architecture, UX, design choices, requirements

Status: **design recap, nothing implemented yet.** The organiser view comes after the Cloudflare setup.

Items marked **(assumed)** were proposed but never explicitly answered. Confirm or change them before coding.

## 1. Scope

A pure utility for the organiser, usable on a phone or a laptop. No effort goes into looks: plain cards on a phone, plain tables on a laptop.

| In scope | Out of scope for this step |
|---|---|
| Read-only monitoring of all teams | Riddle grading (needs a new review table and scoring rules) |
| Event log, riddle answers, challenge notes | Reset or force-advance of a team (stays in the CLI, `flask reset-game`) |
| Validation codes and join codes | Roles (one shared password) **(assumed)** |
| CSV exports | A "not in a team" check (rejected, see section 4) |
| Setting the general-challenges deadline | |

## 2. Architecture

```
Internet -> Cloudflare (Access on /admin) -> cloudflared tunnel -> gunicorn on 127.0.0.1 -> Flask
                                                                              |
                                                       web/admin.py -> db/repo.py -> SQLite
```

Two independent layers protect `/admin`:

| Layer | Role | Where |
|---|---|---|
| **Cloudflare Access** | Keeps bots and strangers out before they reach the app | Cloudflare dashboard, rule on the `/admin*` path (step 9) |
| **App password** | Still required inside the app, so the app is safe on the LAN, in dev, and if Access is misconfigured | `web/auth.py` |

Layering follows the project rule `web -> db -> engine`:

| Layer | Changes |
|---|---|
| `config.py` | Fail-closed `ADMIN_PASSWORD`, `DISPLAY_TZ`, admin session lifetime |
| `web/auth.py` | `admin_required`, admin login and logout, rate-limit key function |
| `web/admin.py` | Login, logout, three tab partials, team drill-down, CSV exports, deadline POST |
| `db/repo.py` | Team overview (phase, score, last activity), answers, filtered and paged events, itinerary codes |
| `engine/` | **No change.** The scoring and state rules are reused as they are. |
| Templates and CSS | Admin base layout, login page, tab partials, one small link on screen A |
| Dependencies | `tzdata` (timezone data is missing on Windows) |

The admin session is **independent of the team session**. Today `login()` in `web/auth.py` calls `session.clear()`, which would log the organiser out when the same browser joins a team. This must be changed so that admin and team flags do not erase each other.

## 3. UX

### Entry
- A small, discreet link below the team list on screen A. It is a plain link with an `aria-label` and a tap target large enough for a thumb.
- The real entrance is the URL `/admin`. It must work from any browser, whether or not that browser has joined a team. This matters because the link disappears once a phone has joined a team.

### Login
- One password field. Wrong attempts show a generic error and are rate-limited.
- A logout button on every admin page.

### Three tabs (HTMX partials)

| Tab | Content | Refresh |
|---|---|---|
| **Teams** | One card per team: name, itinerary, phase, "Location n/N", the expected next code, the deadline as a clock time, score, ticks versus k, wrong-code count, last activity. Tapping a team opens its **drill-down**. A card at the top sets the general-challenges deadline. | Polls every 10 s |
| **Log** | Events newest first, readable sentences with the raw type available. Filter by team. About 200 rows, then "load more". | Polls every 10 s |
| **Codes** | Per itinerary, the ordered steps with their validation codes, plus the teams' join codes. Printable. | Static |

**Team drill-down:** the team's riddle answers and challenge notes, each with its time. A step challenge ticked in a failed step is flagged as scoring nothing.

**CSV exports:** one file of events and one of answers (the review sheet), from the Log tab and the drill-down.

## 4. Design choices

| Topic | Choice | Why |
|---|---|---|
| Not-in-a-team check | **None** | Cheating is not an issue and a cookie is cleared in two seconds. The password is the only gate. It would also lock out an organiser who tested a team on their own phone. |
| Authentication | App password **plus** Cloudflare Access | Defence in depth. The app stays safe without Access (LAN, dev). |
| Empty password | **Never accepted, anywhere** | If `ADMIN_PASSWORD` is empty or still `change-me`, `/admin` answers 404 and login is impossible. The password comparison is constant-time. |
| Rate-limit key for the login | `CF-Connecting-IP`, trusted **only** when the request comes from loopback | Behind the tunnel every request is `127.0.0.1`, so a per-IP key locks everybody out. A global limit would let an attacker lock the organiser out. Cloudflare overwrites that header, and the app listens on localhost only. Falls back to the remote address in dev. |
| Tab layout | 3 tabs with a drill-down for answers | Fits a 390 px screen. Monitoring (live) and review (a long document) are different jobs. |
| Entry point | Small link on screen A **and** the `/admin` URL **(assumed)** | The link is a convenience. The URL is the real entrance. |
| Refresh | HTMX polling, 10 s | 5 teams means trivial load. |
| Timezone | Server-side `DISPLAY_TZ` (default `Europe/Paris`) | One place decides, and the CSV matches the screen. Times are stored in UTC. |
| CSV format | `;` separator, UTF-8 with BOM **(assumed)** | French Excel mangles commas and accents otherwise. `.xlsx` would add a dependency. |
| CSV safety | Cells starting with `=`, `+`, `-` or `@` get a leading `'` | Players type free text. A note starting with `=` would run as a formula in Excel. |
| Step names | Location label, else location text, else step id | Steps have no title, and there is no migration system, so no schema change. |
| Deadline setting | A card on the Teams tab, saved through the existing `repo.set_general_deadline` | The one missing piece from step 4: today it can only be set in code. |
| Audit of the deadline change | Optional small `admin_action` table, created automatically | The `event` table requires a team id, and changing that column needs a table rebuild. **Not decided.** |
| Look and feel | Plain, no polish | Pure utility. |

## 5. Requirements

### Access and security
1. `/admin*` requires login. An empty or placeholder `ADMIN_PASSWORD` disables it (404).
2. The password check is constant-time.
3. Wrong attempts are rate-limited per client, using the key described above.
4. The admin session is independent of the team session in both directions.
5. The admin session expires after a few hours, and a logout button ends it at once.
6. Admin responses carry `Cache-Control: no-store`, because they show codes and answers.
7. No validation code reaches a player. The existing "no code reaches a phone" test stays. A new test checks that anonymous `/admin*` requests get nothing, including the CSV routes.
8. Admin pages escape player-typed text (team names, notes, riddle answers).

### Content
9. Teams tab as in section 3. Each load first resolves lazy expiry for every team (`resolve_team`). Otherwise an idle phone leaves a timed-out step displayed as still running. The call is idempotent, and events are stamped with the deadline, so nothing is distorted.
10. "Last activity" means the last event, not the last request. The page words it that way, since an idle but alive phone looks like a dead one.
11. The drill-down lists riddle answers and challenge notes with times, and flags points lost on failed steps.
12. The Log is newest first, filterable by team, capped, with readable sentences.
13. The Codes tab lists the ordered steps per itinerary with codes, plus join codes.
14. CSV exports of events and of answers, in the format above.
15. The organiser can set and clear the general-challenges deadline. The value is shown in local time, and an invalid value is rejected.

### Non-functional
16. Usable on a phone (cards) and on a laptop (plain tables), without a dedicated desktop layout.
17. Times are shown in `DISPLAY_TZ`.
18. No change to the engine and no schema migration.

## 6. Modifications checklist

| # | Change | Layer |
|---|---|---|
| 1 | `ADMIN_PASSWORD` fail-closed, `DISPLAY_TZ`, admin session lifetime | config |
| 2 | `tzdata` in `pyproject.toml` | dependencies |
| 3 | Split admin and team session flags, so neither clears the other | `web/auth.py` |
| 4 | `admin_required`, login, logout, limiter key function | `web/auth.py` |
| 5 | Team overview, answers, paged events, itinerary codes | `db/repo.py` |
| 6 | Three tab partials, drill-down, CSV exports, deadline POST | `web/admin.py` |
| 7 | Admin base, login page, tab templates, link on screen A | templates |
| 8 | Tests: auth and fail-closed, rate limit, session independence, no-store, tab content, expiry resolved on view, CSV escaping, no-code-leak | tests |
| 9 | README and Datamodel updates | docs |

Suggested order: auth and login, then Teams tab, then Log and CSV, then Codes, then the deadline setting, then the screen A link and the hardening tests.

## 7. Open points

- **Confirm the assumed items** in section 1 and section 4: single password, link plus URL, CSV format, read-only plus deadline.
- **`admin_action` audit table:** keep or drop.
- **Cloudflare first:** the tunnel, the named domain and the Access rule on `/admin*` come before this step is built. The app-level login is still required either way.
