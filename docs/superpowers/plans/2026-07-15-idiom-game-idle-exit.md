# Idiom Game Idle Exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a board-driven presence prompt and device-scoped idle exit without keeping cloud ASR active or closing the persistent game WebSocket prematurely.

**Architecture:** Extend the existing persistent idiom WebSocket with an idle-only `idle_exit` control and acknowledgement. Keep timing and prompt playback on the ESP32 because the board owns VAD/playback state; keep state cleanup on the server because the server owns the device-keyed idiom store.

**Tech Stack:** ESP-IDF 5.5 C/FreeRTOS, ESP WebSocket client, FastAPI WebSocket, Python unittest/pytest, SPIFFS PCM16LE assets.

## Global Constraints

- Work only in `D:\20260709_Tiny_Machine_Robot-merge` on branch `merge`.
- Do not modify the 0701 repository or KWS experiment files.
- Do not stage or commit `esp_idf_demo/main/config.h` or `esp_idf_demo/sdkconfig.multinet_eval`.
- DashScope remains the expected ASR provider; the stale Volcengine assertion is recorded separately if it still fails.
- Do not commit or push until the user explicitly approves after verification.
- Preserve the existing 200 ms game pre-roll, 200 ms trailing-silence upload stop, 200 ms playback echo guard, maximum recording limit, game TTL, ping/pong, reconnect, and normal single-turn chain.

---

### Task 1: Device-scoped idle-exit protocol

**Files:**
- Modify: `src/voice_skills/router.py`
- Modify: `src/api/realtime.py`
- Test: `tests/test_voice_skills.py`
- Test: `tests/test_opus_uplink.py`

**Interfaces:**
- Produces: `SkillRouter.end_idiom_game(device_id: str) -> bool` and `end_idiom_game(device_id: str) -> bool`.
- Consumes: idle WebSocket control `{"type":"idle_exit","event_id":"...","reason":"..."}`.
- Produces: `idle_exit_ack` containing the same `event_id`, the connection `device_id`, `skill_active=false`, `end_skill_state=true`, and `cleared`.

- [ ] **Step 1: Write the failing router isolation test**

Add a test that starts games for `esp-a` and `esp-b`, calls `router.end_idiom_game("esp-a")`, and asserts only `esp-a` is cleared. Call it again and assert it returns `False` without affecting `esp-b`.

- [ ] **Step 2: Run the router test and verify RED**

Run: `python -m pytest tests/test_voice_skills.py -k idle_exit -q`

Expected: failure because `SkillRouter.end_idiom_game` does not exist.

- [ ] **Step 3: Implement the minimal router API**

Add a public method that checks `store.is_active(device_id)`, clears only that key through the existing `IdiomGameSkill.exit`, and returns whether an active state existed. Export a module function through `get_default_skill_router()` for the API layer.

- [ ] **Step 4: Run the router test and verify GREEN**

Run: `python -m pytest tests/test_voice_skills.py -k idle_exit -q`

Expected: the new isolation/idempotency test passes.

- [ ] **Step 5: Write the failing WebSocket protocol test**

Feed an idle `idle_exit` control followed by disconnect into `_FakeWebSocket`, patch the module cleanup function, and assert: no ASR instance is created; cleanup receives only the `X-Device-ID`; the socket emits `idle_exit_ack`; the endpoint does not close the persistent socket itself before the client disconnects.

- [ ] **Step 6: Run the WebSocket test and verify RED**

Run: `python -m pytest tests/test_opus_uplink.py -k idle_exit -q`

Expected: the current endpoint returns `idle_control_message` and never calls cleanup.

- [ ] **Step 7: Implement and verify the idle control**

Handle `idle_exit` only in the outer idle loop, validate a bounded non-empty `event_id`, ignore payload `device_id`, call the device-scoped cleanup function, send the acknowledgement, and continue waiting until the client closes. Run the Step 6 command and expect PASS.

---

### Task 2: ESP idle timer and local prompt state machine

**Files:**
- Modify: `esp_idf_demo/main/config.h` only for guarded default macro definitions; never stage this protected file
- Modify: `esp_idf_demo/main/main.c`
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`
- Test: `tests/test_tiny_esp_guards.py`

**Interfaces:**
- Produces: `cloud_client_idiom_game_idle_exit(client, event_id, reason, ack_timeout_ms)`.
- Timing constants: empty-result prompt floor 1500 ms, post-prompt no-VAD exit 30000 ms, normal no-VAD exit 60000 ms, hard no-usable-turn exit 180000 ms, idle-exit acknowledgement 2000 ms.
- Prompt paths: `/spiffs/idiom_game_presence_1.pcm` and `/spiffs/idiom_game_idle_exit_1.pcm`.

- [ ] **Step 1: Write failing static guard tests**

Assert the main loop contains explicit presence-prompt, post-prompt deadline, normal idle deadline, and hard deadline states; empty-result allowlisting; no prompt for generic recoverable errors; the idle-exit client API; and a branch that closes the socket/restores normal wake flow only after final idle exit.

- [ ] **Step 2: Run the guard tests and verify RED**

Run: `python -m pytest tests/test_tiny_esp_guards.py -k "presence or idle_exit" -q`

Expected: failure because the constants, state fields, and client API are absent.

- [ ] **Step 3: Implement WebSocket idle-exit send/ack**

Add `idle_exit_ack_received` and matching event-id storage to the persistent client. Parse `idle_exit_ack` separately from turn `done/error`. Send the idle control only when no turn is active, wait at most 2000 ms for a matching ack, and leave final socket destruction to the existing close function.

- [ ] **Step 4: Implement the board deadlines**

Track monotonic deadlines in `app_run_idiom_game_loop`. A normal reply playback starts a 60-second no-VAD deadline and 180-second hard deadline. Confirmed VAD pauses the no-VAD deadline. An empty/noise recoverable result waits only the remainder of the 1.5-second floor, plays the presence prompt once, rearms after the 200 ms echo guard, and starts the 30-second no-VAD deadline. A usable `done` resets the prompt flag and deadlines.

- [ ] **Step 5: Implement final local exit**

On a deadline, play the exit PCM with VAD gated, send `idle_exit`, clear `s_local_idiom_context_until_us`, close the existing WebSocket through normal loop cleanup, and return `ESP_OK` so the main loop restores WakeNet. Log deadline kind, device id, ack result, and final action without logging credentials.

- [ ] **Step 6: Run the guard tests and verify GREEN**

Run: `python -m pytest tests/test_tiny_esp_guards.py -q`

Expected: all ESP guard tests pass.

---

### Task 3: Static board prompts

**Files:**
- Create: `esp_idf_demo/spiffs/idiom_game_presence_1.pcm`
- Create: `esp_idf_demo/spiffs/idiom_game_idle_exit_1.pcm`
- Modify: `esp_idf_demo/spiffs_prompt_manifest.json`
- Test: `tests/test_esp_assets.py`

**Interfaces:**
- `idiom_game_presence_1.pcm` text: `你还在吗？`
- `idiom_game_idle_exit_1.pcm` text: `那我们下次再玩吧。`
- Both files: raw signed 16-bit little-endian PCM, 16000 Hz, mono, even byte length, non-empty.

- [ ] **Step 1: Write the failing asset test**

Extend the SPIFFS prompt manifest assertion with both exact texts. Verify both files exist, are non-empty, have even byte length, and fit within the existing 4 MiB SPIFFS partition.

- [ ] **Step 2: Run the asset test and verify RED**

Run: `python -m pytest tests/test_esp_assets.py -k prompt_audio -q`

Expected: failure because the two PCM assets and manifest entries are missing.

- [ ] **Step 3: Generate and add the assets**

Use the already configured DashScope/Qwen TTS environment on the authorized cloud server to synthesize the two exact texts. Convert or capture output as raw PCM16LE 16 kHz mono, copy only the resulting PCM files into `esp_idf_demo/spiffs`, and update the manifest. Do not copy keys, local IPs, or device IDs into the repository.

- [ ] **Step 4: Validate audio format and verify GREEN**

Run: `python -m pytest tests/test_esp_assets.py -k prompt_audio -q`

Expected: both asset tests pass and the manifest text matches exactly.

---

### Task 4: Regression and firmware verification

**Files:**
- Modify: `docs/superpowers/summaries/2026-07-14-persistent-idiom-game-current-state.md` to document the final state only if implementation changes its recorded behavior

**Interfaces:**
- Verification only; no new runtime API.

- [ ] **Step 1: Run targeted cloud and board tests**

Run:

```powershell
python -m pytest tests/test_voice_skills.py tests/test_opus_uplink.py tests/test_tiny_esp_guards.py tests/test_esp_assets.py -q
```

Expected: zero new failures. If the known provider assertion appears in a broader suite, label it as the pre-existing stale Volcengine expectation.

- [ ] **Step 2: Run the existing relevant regression suites**

Run:

```powershell
python -m pytest tests/test_realtime_api.py tests/test_realtime_smoke.py tests/test_idiom_audio_catalog.py -q
```

Expected: zero feature regressions; report every unrelated failure explicitly.

- [ ] **Step 3: Build firmware in the ESP-IDF 5.5 environment**

Run from `esp_idf_demo` with the user's existing non-repository Wi-Fi/server/device configuration:

```powershell
idf.py build
```

Expected: exit code 0 and SPIFFS image contains both new PCM assets.

- [ ] **Step 4: Review protected and intended changes**

Run:

```powershell
git status --short
git diff --check
git diff -- esp_idf_demo/main/config.h
```

Expected: no whitespace errors; `config.h` remains unstaged/local-only; `sdkconfig.multinet_eval` remains untracked and excluded.

- [ ] **Step 5: Report and request commit approval**

List exact passing commands, existing failures, firmware build result, intended stage list, and deployment/burn requirements. Recommend whether the change is ready to submit, but do not stage, commit, push, deploy, or flash until the user explicitly authorizes those actions.
