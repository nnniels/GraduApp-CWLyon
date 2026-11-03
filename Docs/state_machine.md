# State machine

Status: **draft for review**. Once agreed, this file is the contract for `graduapp/engine/`.

## 1. Principles

- The server owns the state. A phone only displays it and sends actions.
- The engine is pure: `transition(state, step, action, now) -> (new_state, events)`. No I/O, and `now` is injected.
- Expected business outcomes are **events, not exceptions**. A wrong code returns the unchanged state and a `CODE_REJECTED` event. Exceptions (`InvalidTransition`) are for actions that should never be possible from the UI: stale clicks, wrong phase.
- Every action carries the `step_index` the client was looking at. A mismatch means a stale screen and is rejected, so a double tap can never skip two steps.
- Expiry is **lazy**. Every action, and every page load, first runs `resolve_expiry(state, now)`.

## 2. State

| Field | Meaning |
|---|---|
| `step_index` | Current step in the team's itinerary (0-based). `== len(steps)` means finished. |
| `phase` | `NOT_STARTED`, `GOING`, `RIDDLE`, `CHALLENGES`, `ENDED` |
| `phase_deadline` | UTC timestamp, set only in `CHALLENGES`, otherwise null |

Stored separately (derived from events or in their own table, see section 7):
- Step challenges ticked, for the current step.
- General challenges ticked, with the proof text.
- General challenges unlocked.

## 3. Phases and diagram

```mermaid
stateDiagram-v2
    [*] --> NOT_STARTED
    NOT_STARTED --> GOING : start (the team itself)

    GOING --> RIDDLE : arrive(code ok) and step.kind = riddle
    GOING --> CHALLENGES : arrive(code ok) and step.kind = challenges
    GOING --> GOING : arrive(code wrong)

    RIDDLE --> GOING : submit_riddle, more steps
    RIDDLE --> ENDED : submit_riddle, last step

    CHALLENGES --> CHALLENGES : tick / untick, ticked < k
    CHALLENGES --> GOING : ticked reaches k (success), more steps
    CHALLENGES --> GOING : deadline passed (failure), more steps
    CHALLENGES --> ENDED : success or failure on last step

    ENDED --> [*]
```

Note: general challenges (screen C) are **orthogonal**. They can be ticked or unticked in `GOING`, `RIDDLE`, `CHALLENGES` and `ENDED`, and never change `phase`.

## 4. Actions

| Action | Allowed in | Guard | Effect |
|---|---|---|---|
| `start` | `NOT_STARTED` | none, each team starts its own game | `step_index = 0`, `phase = GOING` |
| `arrive(code)` | `GOING` | code equals `step.code` | Add `step.unlocks` to the general list. `phase` becomes `RIDDLE`, or `CHALLENGES` with `deadline = now + step.duration`. |
| `submit_riddle(text)` | `RIDDLE` | text not empty | Store the answer (never judged), then advance. |
| `tick_step_challenge(id, text)` | `CHALLENGES` | `now < deadline`, id belongs to the step, not already ticked | Tick it. If ticked count `>= k`, success and advance. |
| `untick_step_challenge(id)` | `CHALLENGES` | `now < deadline`, ticked | Untick it. |
| `tick_general(id, text)` | any started phase | unlocked, not already ticked | Tick it. |
| `untick_general(id)` | any started phase | ticked | Untick it. |
| `resolve_expiry` | implicit, before every action and page load | `phase = CHALLENGES` and `now >= deadline` | Step failure, then advance. |

**Advance** means: `step_index += 1`. If it equals `len(steps)`, `phase = ENDED`. Otherwise `phase = GOING`, and the deadline is cleared.

## 5. Events (append-only log)

Each transition returns the events to persist, in the same transaction as the new state.

| Event | Payload | Raised by |
|---|---|---|
| `GAME_STARTED` | | `start` |
| `CODE_REJECTED` | step_index, code entered | `arrive` |
| `ARRIVED` | step_index | `arrive` |
| `CHALLENGES_UNLOCKED` | challenge ids | `arrive` |
| `CHALLENGE_PHASE_STARTED` | step_index, deadline | `arrive` |
| `RIDDLE_ANSWERED` | step_index, text | `submit_riddle` |
| `CHALLENGE_TICKED` | scope (`step`/`general`), id, text | tick actions |
| `CHALLENGE_UNTICKED` | scope, id | untick actions |
| `STEP_SUCCEEDED` | step_index, ticked count | k reached, or riddle answered |
| `STEP_FAILED` | step_index, ticked count | expiry |
| `GAME_ENDED` | | advance past the last step |

## 6. Edge cases and decisions

| Case | Rule | Why |
|---|---|---|
| Tick arrives after the deadline | Expiry is resolved first, then the tick is rejected as stale. | The server clock is the only clock. |
| Network lag at the last second | No grace period in v1. | Simple. Add a few seconds later if teams complain. |
| Double tap on "I am here" | Second request has an old `step_index` or wrong phase, so it is rejected. | Idempotent, nothing skipped. |
| Untick after step end | Rejected. Step challenges are frozen once the step closes. | The score was already decided. |
| Untick a general challenge | Always allowed, with the confirm popup. | Matches the spec. |
| Page reload or phone swap | The state is re-rendered from the DB. | The server owns the state. |
| `k` reached | Advance immediately, no further ticks. | Matches the spec. |
| Same itinerary shared by two teams | Fine. State is per team, and codes are per step. | You confirmed codes are per step. |
| Wrong code | Unlimited, but rate-limited by the web layer. Every attempt is logged. | Friendly game. |

## 7. Consequences for the other layers

- **DB (`schema.sql`)**: `team`, `team_state` (the 3 fields above), `event`, `challenge_completion(team_id, scope, step_index, challenge_id, text, ticked_at, unticked_at)`, and `unlocked_challenge(team_id, challenge_id)`.
- **Content schema**: a step has `id`, `location`, `code`, `unlocks[]`, and exactly one of `riddle` or `challenges{ items[], k, duration_s }`.
- **Errors**: `WrongCode` becomes unnecessary and will be removed from `engine/errors.py`. `InvalidTransition` stays.
- **Scoring**: computed from events (see below).

## 8. Scoring proposal (computed, not stored)

- Each challenge has `points` in the YAML (default 1).
- General challenges: points of each ticked and not unticked challenge.
- Step challenges: points only if the step ended in `STEP_SUCCEEDED`. A failed step still advances (and its unlocks are still given) but brings no points home.
- `step.points` is a bonus added for each `STEP_SUCCEEDED`.
- Riddles: points are awarded when the gamemaster reviews them, so they are **not** in the computed score for now.
- Time is a possible tie-breaker (`GAME_ENDED.ts - GAME_STARTED.ts`).

## 9. Open questions

Resolved: each team starts its own game; riddles have no timer; a failed step still advances and unlocks, but scores nothing.

1. **After `ENDED`**, should general challenges stay tickable? I lean towards yes, until the organiser closes the game.
