<span style="color:#99BBFF">
Ok, let's not get side-tracked and stick to the plan. let's move on to item number 4 of the main plan.
Before coding anything, explain what step 4 is about. then, compare step 4 of the main plan to the 'proposed order' sequence you just wrote. Is one included in the other ?
Be concise and delivery-orientated in your answer.
</span>




# Step 4: Team identity

**What it is:** how the server knows which team a phone is, and keeps strangers out.

| Part | Content |
|---|---|
| Screen A | Team list, editable name, code field, Confirm button |
| Join code check | Verified on the server before anything else happens |
| Signed session cookie | Holds `team_id`, so reloads and later requests stay logged in as that team |
| Team lock | Once confirmed, `/` goes straight to B. The phone can't pick another team without the code. |

**Delivered when:** a phone picks a team, enters the right code and is recognised on every later request. A wrong code is refused and counted.

## Step 4 vs. my "proposed order"

**Yes, step 4 is included in the proposed order. The proposed order is wider.**

| Proposed order item | Part of step 4? |
|---|---|
| 1. `TEAM_JOINED` / `TEAM_RENAMED` events | ✅ Yes. They log who joined, so a team is traceable. |
| 2. DB per request, secret-key guard | ✅ Yes. Needed infrastructure, and the guard protects the cookie. |
| 3. Screen A and join route with cookie | ✅ Yes. This is the core of step 4. |
| 4. Screen B stub | ❌ No. This is the start of **step 5**. |
| 5. Rate limit | ✅ Yes. It is the "10 attempts" rule on the code check. The battle plan puts it in step 9, but it belongs here. |
| 6. `flask show-events` | ❌ No. A dry-run tool, close to a minimal slice of step 8. |
| 7. Web tests and phone test | ✅ Yes, as the validation of step 4. |

**Summary**
- **Step 4 itself:** items 1, 2, 3, 5 and 7.
- **Borrowed from step 5:** item 4. Without any destination, screen A has nothing to show after the redirect.
- **Borrowed from step 8:** item 6, to check the data by hand.
- **Moved up from step 9:** the rate limit, because the code check is useless without it.

I'd keep the B stub to a few lines: team name and current phase, with no modes and no buttons. That keeps step 5 intact.

Shall I proceed with items 1, 2, 3, 5 and 7, plus the stub and `show-events`?

---

hophophop

---

Step 4 is done: a phone can pick a team on screen A, enter the code and be recognised afterwards. All 107 tests pass. I also ran the real dev server and drove it with `curl` against a temporary database, which I deleted afterwards. The result matched the tests:
- A wrong code returned 403.
- The right code returned a 303 redirect and set the cookie.
- The database held the expected events: `JOIN_REJECTED`, `TEAM_RENAMED` and `TEAM_JOINED`.

I did not test from a real phone. That check is yours.

**What was built (items 1, 2, 3, 5, 7)**
- **Join events (item 1):** `repo.join_team` checks the code, renames the team if asked, and logs `TEAM_JOINED`, `TEAM_RENAMED` and `JOIN_REJECTED` in one transaction. These are not engine events, and scoring ignores them.
- **Per-request DB (item 2):** `web/db.py` opens one connection per request. The app now refuses to start without a `SECRET_KEY` unless it is in debug or test mode.
- **Screen A (item 3):** `team_select.html` shows one card per team. Each card has its own name field, code field and Confirm button. No JavaScript is needed.
- **Team lock (item 3):** after joining, `/` shows `team_locked.html`, a one-line "registered for your team" page. This is not the screen B stub. It is just the destination for the redirect.
- **Cookie (item 3):** Flask's signed session, HttpOnly, SameSite=Lax, lasting 2 days. `COOKIE_SECURE=1` turns on the Secure flag for the tunnel.
- **Rate limit (item 5):** 10 wrong codes per 10 minutes. Only wrong codes count, and a locked team gets a 429 even with the right code.
- **Tests (item 7):** 23 new web tests and 4 new repo tests. The old smoke test is replaced by the new web tests.

**Two decisions I made, and one bug I fixed**
- **Rate limit per team, not per IP.** Behind the tunnel every request looks like it comes from `127.0.0.1`, so a per-IP limit would lock everyone out together. The drawback is that someone can burn another team's attempts. That is acceptable for a friendly game.
- **A name check that leaked the code.** If the name had been checked after the code, a 400 versus a 403 would have told an attacker the code was right, without costing an attempt. The name is now checked first, and tests cover it.
- **Blank-name bug.** A whitespace-only name was refused as invalid instead of keeping the current name. Fixed in the route.

**Known limits**
- **Rate-limit counters are in memory.** A restart resets them, as expected.
- **No CSRF token.** `SameSite=Lax` covers most of the risk. I'll revisit this in hardening.
- **No logout.** On the phone, clear the browser cookies to pick another team.

Two process slips: I created two stray files by mistake (`__init__.py.new` and `team_select_new.html`) and removed both. Nothing is committed yet, so `git status` shows the changes. The next steps are the screen B stub and `flask show-events` in step 5, then the phone test.