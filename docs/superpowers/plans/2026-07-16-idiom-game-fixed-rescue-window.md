# Idiom Game 15+10 Second Attempt Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the idiom game's `25/20/30/60` idle policy with a 15-second base attempt budget plus one 10-second rescue bonus, for at most 25 seconds of user-interaction time per round.

**Architecture:** Keep the persistent WebSocket, MultiNet buffering, Opus framing, and ASR capture termination unchanged. Track `remaining_attempt_budget_us` on the board, subtract VAD-wait and active-turn time, pause accounting during robot playback and echo guard, grant the rescue bonus once, and reset only after `meaningful`.

**Tech Stack:** ESP-IDF 5.5.4, C, FreeRTOS monotonic timers, pytest source guards, existing SPIFFS PCM assets.

## Global Constraints

- Work only in `D:\20260709_Tiny_Machine_Robot-merge` on branch `merge`.
- Do not stage or modify local `esp_idf_demo/main/config.h` as part of this feature.
- Keep game recording termination at 200ms trailing silence or the existing approximately four-second total-audio ceiling.
- Do not change DashScope ASR selection, TTS providers, WebSocket message schema, `device_id`, or `turn_id` behavior.
- Do not create runtime dynamic TTS in idiom mode.
- Do not commit or push until the user explicitly approves submission.

---

### Task 1: Lock the budget policy with failing guards

**Files:**
- Modify: `tests/test_tiny_esp_guards.py`

**Interfaces:**
- Consumes: firmware sources as UTF-8 text.
- Produces: failing guards for 15+10 constants, one-time rescue grant, budget consumption, bounded VAD waits, and suppression of repeated nonmeaningful replies.

- [x] Replace old timing expectations with:

```python
assert "#define APP_IDIOM_GAME_BASE_ATTEMPT_MS 15000" in main
assert "#define APP_IDIOM_GAME_RESCUE_BONUS_MS 10000" in main
assert "APP_IDIOM_GAME_NORMAL_IDLE_MS" not in main
assert "APP_IDIOM_GAME_POST_PRESENCE_IDLE_MS" not in main
assert "APP_IDIOM_GAME_POST_NONMEANINGFUL_IDLE_MS" not in main
assert "APP_IDIOM_GAME_NOISE_HARD_IDLE_MS" not in main
```

- [x] Require `remaining_attempt_budget_us`, `rescue_active`, budget-consumption helpers, and `action=attempt_budget_preserved` in the game loop.
- [x] Require the first nonmeaningful result to use local `idiom_game_misheard`, while `game_ended || !outcome_nonmeaningful` prevents streaming invalid/off-topic server audio.
- [x] Require repeated nonmeaningful branches to omit the rescue-grant helper and preserve the current balance.
- [x] Require the game VAD function to accept a caller-provided timeout and retain `AUDIO_IN_GAME_TRAILING_SILENCE_MS 200` plus `DEMO_RECORD_DURATION_SEC 4`.
- [x] Run `python -m pytest tests/test_tiny_esp_guards.py -q` and verify RED because the old constants and hard deadline remain.

### Task 2: Implement budget-aware game VAD waiting

**Files:**
- Modify: `esp_idf_demo/main/audio_in.h`
- Modify: `esp_idf_demo/main/audio_in.c`
- Modify: `esp_idf_demo/main/main.c`
- Test: `tests/test_tiny_esp_guards.py`

**Interfaces:**
- Consumes: `remaining_attempt_budget_us` from the game loop.
- Produces: `audio_in_wait_for_game_speech_start(..., uint32_t timeout_ms)` whose wait ceiling is `min(3000ms, remaining budget)`.

- [x] Add `timeout_ms` to the game-only VAD wait declaration and definition; reject zero and calculate `timeout_at_us` from this argument.
- [x] Add a helper that rounds remaining microseconds up to milliseconds and caps the result at `DEMO_WAIT_FOR_SPEECH_TIMEOUT_MS`.
- [x] Keep `audio_in_stream_game_after_speech_start()` byte-for-byte unchanged so 200ms tail silence and the four-second buffer ceiling are unaffected.
- [x] Run the focused guard and confirm the signature/timing assertions pass while state-machine assertions remain RED.

### Task 3: Implement the 15+10 attempt budget

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Test: `tests/test_tiny_esp_guards.py`

**Interfaces:**
- Consumes: `turn_outcome` and recoverable empty-ASR error codes.
- Produces: a single remaining-budget counter and one-time rescue bonus.

- [x] Replace old timeout constants with:

```c
#define APP_IDIOM_GAME_BASE_ATTEMPT_MS 15000
#define APP_IDIOM_GAME_RESCUE_BONUS_MS 10000
```

- [x] Initialize each cycle with `remaining_attempt_budget_us = APP_IDIOM_GAME_BASE_ATTEMPT_MS * 1000`, `rescue_active=false`, and no rescue reason.
- [x] Subtract elapsed VAD waiting immediately after every game VAD call.
- [x] Subtract time from confirmed VAD through local/ASR result availability before any robot playback.
- [x] Preserve active-turn overrun as negative balance so the one-time rescue bonus first repays that debt instead of extending the 25-second interaction ceiling.
- [x] When base balance reaches zero without a prior prompt, play presence, grant exactly 10 seconds, and mark rescue active.
- [x] On the first `empty / invalid / off_topic`, play local misheard, grant exactly 10 seconds on top of the remaining base balance, and mark rescue active.
- [x] During rescue, suppress repeated nonmeaningful audio and never grant or reset budget.
- [x] On `meaningful` or legacy success, play the response and reset to a fresh 15-second base balance.
- [x] If rescue balance is exhausted, do not begin another ASR; allow an already-started turn to finish, then exit unless meaningful.
- [x] Keep explicit exit and `end_skill_state` behavior unchanged.
- [x] Run `python -m pytest tests/test_tiny_esp_guards.py tests/test_opus_uplink.py -q` and verify GREEN except the separately documented stale Volcengine assertion if selected.

### Task 4: Documentation and regression verification

**Files:**
- Modify: `docs/superpowers/summaries/2026-07-16-idiom-game-noise-circuit-breaker-current-state.md`
- Verify: all intended files

**Interfaces:**
- Consumes: final implementation.
- Produces: durable current-state report and validation evidence.

- [x] Replace 25/20/30/60 behavior with the confirmed 15+10 balance model and state that playback/echo do not consume balance.
- [x] Run focused cloud/ESP regressions:

```powershell
python -m pytest tests/test_tiny_esp_guards.py tests/test_esp_assets.py tests/test_opus_uplink.py tests/test_realtime_api.py tests/test_voice_skills.py -q
```

- [x] Run `git diff --check` and verify `config.h` is not part of the feature diff.
- [x] Run the full Python suite, separately identify only the known stale Volcengine assertion, and run the exact suite with that assertion deselected.
- [x] Build from `D:\20260709_Tiny_Machine_Robot-merge\esp_idf_demo` with ESP-IDF 5.5.4 using `idf.py build`.
- [x] Review the intended scope: `main.c`, `audio_in.c`, `audio_in.h`, `test_tiny_esp_guards.py`, the design, plan, and current-state report.
- [x] Report whether the changes are safe to commit, but do not stage, commit, push, deploy, or flash without explicit user instruction.
