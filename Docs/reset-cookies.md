# What is happening

**Almost certainly this: your browser still has the login cookie, and the reset doesn't touch it.**

1. **The cookie is stored in the browser.** When you joined Team 1, Flask stored `team_id=team-1` in a signed `session` cookie. It is set as permanent and lasts 2 days.
2. **The reset doesn't touch cookies.** `reset-game` only changes the database, and it can't reach a cookie in a browser.
3. **The cookie is still valid.** Cookies are signed with `SECRET_KEY`. If the key hasn't changed, the signature still checks out. That holds if your `.env` key is unchanged. It also holds in `--debug` with no key set, because the fallback key is a fixed string.
4. **The team still exists in the database.** `reset-game` keeps teams and join codes. `current_team()` finds `team-1`, so `/` renders its game page. After a reset that page is the "Start the game" screen, which is what you saw.

So the app did what it was designed to do: the phone stays logged in and the game state was reset underneath it. Only the stale-cookie case where the team no longer exists sends you back to screen A, and a reset never causes that.

**To confirm:** open the page in a private window, or delete the `session` cookie in DevTools (Application → Cookies). You should get screen A. Note that `localhost` and `127.0.0.1` keep separate cookies, so they can show different states.

## Is it a problem?

It depends on the situation:
- **Mid-game:** keeping the login is a feature, because a phone that reloads or restarts must stay on its team.
- **After a full reset (test runs, rehearsal):** it is a nuisance. Every test phone stays logged in as its old team, and the team lock is enforced by the cookie, so someone could be stuck on the wrong team.

## Options

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Do nothing** | Clear cookies by hand on each phone | Zero code | Easy to forget on 5 phones before an event |
| **B. Reset epoch (recommended)** | Store a counter in `game_setting`, copy it into the cookie at login, and bump it on `reset-game`. A cookie with an old counter is dropped, so every phone returns to screen A. | One reset logs out all phones, nothing for people to do | A few lines in auth, plus tests |
| **C. `/logout` route** | A link or button that clears the cookie | Handy for testing, and a phone can leave a wrong team | Per phone, and it must stay out of the player's way |
| **D. Make `--names` also log everyone out** | Same as B, but only with the flag | Matches "full reset" | Odd rule, because names and sessions are unrelated |

I'd choose **B**, with an optional `--keep-sessions` flag if you ever want a reset that doesn't log phones out. C is worth adding only if you want a way to switch team without clearing the cookie. Should I implement B?