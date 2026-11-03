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