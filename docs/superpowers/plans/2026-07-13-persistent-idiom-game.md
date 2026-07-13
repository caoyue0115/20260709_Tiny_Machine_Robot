# Persistent Idiom Game Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents for this repository task.

**Goal:** Add a wake-free, multi-turn idiom game over one persistent board/cloud WebSocket while preserving the existing coffee single-turn path and eliminating runtime dynamic TTS from idiom mode.

**Architecture:** Keep the existing single-turn realtime endpoint unchanged at its boundary and add a dedicated persistent idiom endpoint that owns one ASR/Opus runtime per active `turn_id`. Keep idiom state in the existing process-local `device_id` store, validate and filter static audio at startup, and add an explicit ESP32-S3 game state machine with local VAD, real pre-roll, and per-turn upload.

**Tech Stack:** Python 3, FastAPI WebSocket, pytest/unittest, ESP-IDF C, ESP-SR MultiNet/WakeNet, framed Opus, existing realtime session store and static PCM/WAV pipeline.

## Global Constraints

- Work only in `D:\20260709_Tiny_Machine_Robot-merge` on `feature/coffee-base-idiom-static-audio`.
- Do not modify the 0701 repository, KWS experiment files, `esp_idf_demo/main/config.h`, or `esp_idf_demo/sdkconfig.multinet_eval`.
- Preserve the ordinary coffee wake-and-single-turn endpoint and behavior.
- The persistent connection is not persistent recording: no cloud ASR exists while the game socket is idle.
- Every per-turn server response carries and echoes the board-generated `turn_id`.
- Idiom mode never calls runtime dynamic TTS.
- Do not commit or push until the user explicitly says the changes may be committed.
- At each commit gate, report `建议提交` or `暂不建议提交`, the exact file scope, test evidence, and a suggested commit message.

---

### Task 1: Idiom State, Compact Replies, and Ordered Intent Handling

**Files:**
- Modify: `src/voice_skills/idiom_game.py`
- Modify: `src/voice_skills/router.py`
- Modify: `src/providers/llm.py`
- Modify: `tests/test_voice_skills.py`

**Interfaces:**
- Extend `IdiomGameState` with `last_robot_word: str`.
- Extend `IdiomJudgeDecision` with `intent: str` and `matches_expected_pinyin: bool` while retaining `word`, `first_py`, `last_py`, `confidence`, and `is_idiom`.
- `judge_idiom_answer(raw_text: str, expected_py: str) -> dict | None` returns the approved structured enum contract.
- `IdiomGameSkill.handle(device_id: str, text: str) -> str` keeps the public signature but records an event-rich trace used to build the exact static plan.
- `build_idiom_audio_plan(answer_text: str, trace: dict | None = None) -> list[str] | None` maps events to static segments without pinyin prompts for normal turns.

- [ ] **Step 1: Add failing compact-reply and state tests**

Add focused tests that use a deterministic RNG/opening pool and a small idiom list:

```python
def test_start_plan_has_only_prefixes_and_opening_idiom():
    result = router.route(device_id="esp-1", text="开始成语接龙", trace={})
    assert result.audio_plan == [
        "idiom_game/start",
        "idiom_game/robot_first",
        f"idioms/{opening_word}",
    ]
    assert "轮到你" not in result.answer_text
    assert store.get("esp-1").last_robot_word == opening_word

def test_successful_turn_returns_only_robot_idiom():
    result = router.route(device_id="esp-1", text=user_word, trace={})
    assert result.answer_text == robot_word
    assert result.audio_plan == [f"idioms/{robot_word}"]
    assert store.get("esp-1").last_robot_word == robot_word
```

- [ ] **Step 2: Add failing deterministic control tests**

Parameterize exit expressions including `退出`, `不玩了`, `结束游戏`, `结束接龙`, `先这样`, and `停止`. Parameterize repeat expressions including `没听清`, `没听到`, `再说一次`, `重复一下`, and `刚才是什么`. Assert exits clear state before dictionary lookup; repeats return only `last_robot_word`, keep `expected_py`, `used_words`, and `valid_user_turns` unchanged, and use one idiom audio segment.

- [ ] **Step 3: Add failing LLM enum and validation tests**

Inject one judge callback per intent and assert:

```python
assert accepted_when_idiom == (
    decision.intent == "idiom"
    and decision.is_idiom
    and four_han_characters(decision.word)
    and decision.confidence >= configured_threshold
    and normalize_pinyin(decision.first_py) == state.expected_py
    and bool(normalize_pinyin(decision.last_py))
)
```

Cover `exit`, `repeat`, `easy`, `hard`, `invalid`, `off_topic`, malformed four-character text, missing pinyin, mismatched normalized first pinyin, and low confidence. Verify `matches_expected_pinyin` never determines acceptance.

- [ ] **Step 4: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_voice_skills.py -q
```

Expected: failures show the old prompt-rich plans, missing `last_robot_word`, and the old boolean-only LLM contract.

- [ ] **Step 5: Implement minimal ordered intent logic and compact plans**

Update the start/turn text, state copying, repeat behavior, broad deterministic patterns, LLM prompt/parser, server-side pinyin validation, and trace-to-audio mapping. Ensure control decisions branch before `_extract_user_entry()` and local dictionary lookup remains before `_judge_unknown_entry()`.

- [ ] **Step 6: Run Task 1 tests and existing voice-skill tests GREEN**

Run:

```powershell
python -m pytest tests/test_voice_skills.py tests/test_prebuild_idiom_static_audio.py -q
```

Expected: all selected tests pass and normal plans contain neither `turn_prompt` nor `pinyin/*`.

- [ ] **Step 7: Commit gate**

Do not commit. Report whether Task 1 is independently ready, list its files, and suggest `feat: simplify idiom turns and control intents` only if tests are green.

---

### Task 2: Static Audio Catalog, Format Validation, and No-TTS Enforcement

**Files:**
- Create: `src/voice_skills/idiom_audio.py`
- Modify: `src/providers/static_audio.py`
- Modify: `src/voice_skills/router.py`
- Modify: `src/services/realtime_session.py`
- Modify: `src/app.py`
- Modify: `scripts/prebuild_idiom_static_audio.py`
- Modify: `tests/test_voice_skills.py`
- Modify: `tests/test_prebuild_idiom_static_audio.py`
- Create: `tests/test_idiom_audio_catalog.py`

**Interfaces:**
- `validate_static_audio_segment(segment_id: str, root: Path | None = None) -> Path` opens the asset and raises `StaticAudioError` unless it is readable 16 kHz, mono, signed 16-bit PCM/WAV.
- `IdiomAudioCatalog` exposes `playable_words`, `invalid_fixed_segments`, and `static_error_segment`.
- `build_idiom_audio_catalog(idioms: Iterable[IdiomEntry], root: Path | None = None) -> IdiomAudioCatalog` fails only when `idiom_game/static_error` is unusable, records unusable fixed segments, and excludes unusable idiom words.
- The default router is constructed with the catalog's playable words so opening/reply indexes cannot select missing idiom audio.

- [ ] **Step 1: Add failing format-validation tests**

Generate temporary WAV fixtures and assert valid `16000/1/16-bit` passes while `8000 Hz`, stereo, 8-bit, truncated, missing, and unreadable files fail. Test `.pcm` according to the repository's fixed raw PCM contract.

- [ ] **Step 2: Add failing catalog filtering and fallback tests**

Create two idioms with only one valid asset. Assert only the playable word remains selectable. Assert a missing fixed `mode_easy` is recorded and maps to `idiom_game/static_error`. Assert missing/invalid `static_error` raises during startup catalog construction. Assert `pinyin/*` is never inspected.

- [ ] **Step 3: Add failing no-dynamic-TTS regression test**

Route an idiom result whose fixed plan is unavailable and patch `stream_realtime_tts_chunks` and `synthesize_audio` to raise if called. Assert the session queues `static_error` audio and finishes without either TTS function.

- [ ] **Step 4: Run Task 2 tests and verify RED**

Run:

```powershell
python -m pytest tests/test_idiom_audio_catalog.py tests/test_voice_skills.py tests/test_prebuild_idiom_static_audio.py -q
```

Expected: failures identify missing validator/catalog/startup hook and the current dynamic-TTS fallback.

- [ ] **Step 5: Implement validator, catalog, fixed assets, and startup hook**

Add fixed prebuild entries for `mode_easy`, `mode_hard`, `continue_prompt`, retry, and `static_error`. Build the catalog in FastAPI lifespan/startup before serving requests. Feed `playable_words` into `IdiomGameSkill`; use `robot_no_reply_user_win` when the filtered reply pool is empty. In `realtime_session`, special-case `skill_name == "idiom_game"` so unresolved plans use the validated static error and never enter dynamic TTS.

- [ ] **Step 6: Run Task 2 tests GREEN**

Run the Task 2 command again. Expected: all pass with explicit trace fields for invalid fixed assets and no dynamic TTS calls.

- [ ] **Step 7: Commit gate**

Do not commit. Suggest `feat: validate idiom static audio at startup` only when tests are green.

---

### Task 3: Persistent Multi-Turn Idiom WebSocket

**Files:**
- Modify: `src/api/realtime.py`
- Optionally create: `src/services/idiom_game_stream.py` if extraction keeps the route focused
- Modify: `src/models/realtime.py`
- Modify: `tests/test_opus_uplink.py`
- Modify: `tests/test_tiny_realtime_chain.py`

**Interfaces:**
- New endpoint: `/api/v5/realtime/idiom-game/opus-stream` with the same device/auth/query conventions as the existing Opus route.
- Control messages: `{"type":"utterance_start","turn_id":"..."}` and `{"type":"utterance_end","turn_id":"..."}`.
- Per-turn state owns decoder, ASR provider, frame counters, and limits; idle connection owns no ASR.
- Server messages `asr_final`, `error`, and `done` include the active/request `turn_id`.
- `done` includes `skill_name`, `skill_active`, `end_skill_state`, and `audio_stream_url` and does not close the WebSocket.

- [ ] **Step 1: Add a failing two-turn connection test**

Feed one fake WebSocket two complete control/binary/control sequences followed by disconnect. Assert two distinct `asr_final` and `done` pairs, matching `turn_id`s, and no server close after the first `done`.

- [ ] **Step 2: Add failing ASR lifecycle test**

Use a fake provider recording construction, input, finish, final, and close events. Assert no instance at connect/idle; one instance at `utterance_start`; `utterance_end` calls finish, waits for final or timeout, then closes; the next turn receives a fresh instance.

- [ ] **Step 3: Add failing recovery and stale-message tests**

Cover decoder failure, ASR failure, duplicate start, mismatched end `turn_id`, idle late end, and idle binary. Active-turn failures must emit a recoverable error, release only that turn, retain `device_id` game state, and accept a later valid start. Idle stray messages must be discarded without allocating or destroying a future turn.

- [ ] **Step 4: Run WS tests and verify RED**

Run:

```powershell
python -m pytest tests/test_opus_uplink.py tests/test_tiny_realtime_chain.py -q
```

Expected: the new endpoint/helper is absent and the current single-turn route closes after `done`.

- [ ] **Step 5: Extract reusable single-turn processing and implement persistent loop**

Reuse the existing framed Opus decoder, provider selection, ASR event production, session creation, and board-done payload builder. Keep `/api/v5/realtime/opus-stream` behavior unchanged. For the idiom route, keep connection-level state separate from optional active-turn state and clear only active-turn resources on recoverable errors.

- [ ] **Step 6: Run Task 3 and ordinary realtime tests GREEN**

Run:

```powershell
python -m pytest tests/test_opus_uplink.py tests/test_tiny_realtime_chain.py tests/test_realtime_api.py tests/test_realtime_smoke.py -q
```

Expected: all pass; ordinary route still closes as before, idiom route remains open.

- [ ] **Step 7: Commit gate**

Do not commit. Suggest `feat: add persistent idiom game websocket` only with both persistent and ordinary regression tests green.

---

### Task 4: MultiNet Command Scope

**Files:**
- Modify: `esp_idf_demo/main/local_command_service.c`
- Modify: `esp_idf_demo/main/local_command_service.h`
- Modify: `esp_idf_demo/main/main.c`
- Modify: `tests/test_tiny_esp_guards.py`

**Interfaces:**
- Command IDs `100-102` are start, `110-111` easy, `120-121` hard, and `140-144` repeat.
- IDs `130/131` and `LOCAL_COMMAND_KIND_IDIOM_EXIT` are removed.
- Add `LOCAL_COMMAND_KIND_IDIOM_REPEAT`.
- `app_local_command_should_intercept()` accepts start globally after wake and accepts mode/repeat only when local idiom context is active.

- [ ] **Step 1: Add failing source-guard tests**

Assert the command table lacks `{130,` and `{131,`, contains every ID `140-144` with canonical repeat text, and the intercept function scopes both mode and repeat to active idiom context.

- [ ] **Step 2: Run guard tests and verify RED**

Run:

```powershell
python -m pytest tests/test_tiny_esp_guards.py -q
```

Expected: failures show current exit commands and missing repeat commands.

- [ ] **Step 3: Update command table, enum, and scope logic**

Remove exit interception completely. Map all five repeat phrases to a canonical deterministic text accepted by the cloud router. Preserve pass-through behavior when MultiNet has no accepted result so the already captured PCM continues to ASR.

- [ ] **Step 4: Run ESP guards GREEN**

Run the Task 4 command again. Expected: all guards pass and no protected config file changes appear.

- [ ] **Step 5: Commit gate**

Do not commit. Suggest `feat: scope idiom MultiNet repeat commands` only when green.

---

### Task 5: Board Local VAD, Real Pre-Roll, and Persistent Cloud Client

**Files:**
- Modify: `esp_idf_demo/main/audio_in.h`
- Modify: `esp_idf_demo/main/audio_in.c`
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`
- Modify: `tests/test_tiny_esp_guards.py`
- Modify: `tests/test_esp_assets.py` only if public source guards belong there

**Interfaces:**
- Add a game-listen audio API that keeps at least `DEMO_AUDIO_SAMPLE_RATE * 200 ms` of real PCM in a ring buffer while locally armed and invokes callbacks only after speech start.
- Add a persistent game socket API with explicit `connect`, `begin_turn(turn_id)`, `send_pcm`, `end_turn(turn_id)`, `wait_done(turn_id)`, heartbeat, reconnect, and `close` operations.
- Extend the board session result with `skill_name`, `skill_active`, `end_skill_state`, and returned `turn_id`.

- [ ] **Step 1: Add failing pre-roll and 200 ms silence guards**

Assert the ring capacity is at least 200 ms of PCM, samples are copied into the ring before threshold detection, the flushed prefix is real ring data rather than zero padding, and game trailing-silence duration is 200 ms. Assert playback/echo-guard states cannot call the upload callback.

- [ ] **Step 2: Add failing persistent-client protocol guards**

Assert control JSON contains `utterance_start`, `utterance_end`, and `turn_id`; response parsing requires matching `turn_id`; `done` parses all four required skill fields; and `finish turn` does not destroy the WebSocket handle.

- [ ] **Step 3: Run ESP guards and verify RED**

Run:

```powershell
python -m pytest tests/test_tiny_esp_guards.py tests/test_esp_assets.py -q
```

Expected: failures show the current single-turn begin/finish API and lack of game ring-buffer guarantees.

- [ ] **Step 4: Implement game audio capture and persistent client lifecycle**

Keep existing coffee recording/uplink functions intact. Add game-specific APIs that open the microphone locally after echo guard, maintain the ring buffer without upload, send start before flushing pre-roll, stream Opus only while active, stop at 200 ms low energy or maximum duration, signal end, and keep the socket idle afterward. Treat mismatched `done` as stale and continue waiting for the current turn within the existing timeout.

- [ ] **Step 5: Run Task 5 tests GREEN**

Run the Task 5 command again. Expected: all guards pass with no `config.h` edits.

- [ ] **Step 6: Commit gate**

Do not commit. Suggest `feat: add persistent idiom board transport` only when green.

---

### Task 6: ESP32-S3 Persistent Game State Machine

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Modify: `tests/test_tiny_esp_guards.py`

**Interfaces:**
- Add explicit game states for socket idle, playback, echo guard, VAD armed, upload, and wait reply.
- Enter the game loop when a normal response reports `skill_name == "idiom_game"` and `skill_active == true`.
- Exit the loop on matching `done.end_skill_state == true`, close the game socket, clear local idiom context, and return to WakeNet.

- [ ] **Step 1: Add failing state-transition guards**

Assert source-level transitions enforce playback before echo guard, echo guard before VAD armed, start control before audio upload, end control after 200 ms low energy, and WakeNet restoration only after end state. Assert ordinary coffee handling still calls the existing single-turn function.

- [ ] **Step 2: Add failing reconnect/TTL/limit guards**

Assert game reconnect retains `device_id`, uses bounded retry/backoff, preserves ping/pong, enforces local TTL and maximum recording, and does not clear cloud game state on a recoverable turn error.

- [ ] **Step 3: Run guards and verify RED**

Run:

```powershell
python -m pytest tests/test_tiny_esp_guards.py -q
```

Expected: failures identify the absent persistent game loop.

- [ ] **Step 4: Implement the minimal state machine**

Integrate the Task 5 APIs without restructuring unrelated coffee stages. During reply playback and the 200 ms echo guard, keep upload disabled. During local VAD armed, keep only microphone/VAD/ring activity. On active speech, perform one turn and play its session audio. On end state or TTL, close the game socket and re-arm WakeNet.

- [ ] **Step 5: Run ESP guards GREEN**

Run the Task 6 command again. Expected: all state guards pass.

- [ ] **Step 6: Commit gate**

Do not commit. Suggest `feat: add wake-free idiom game loop` only when green.

---

### Task 7: Full Verification, Build, and Deployment Readiness

**Files:**
- Modify only files required to fix regressions exposed by the commands below.
- Do not modify protected local configuration.

**Interfaces:**
- No new interface; this task proves the integrated contract and prepares deployment evidence.

- [ ] **Step 1: Run focused Python suites**

```powershell
python -m pytest tests/test_voice_skills.py tests/test_idiom_audio_catalog.py tests/test_prebuild_idiom_static_audio.py tests/test_opus_uplink.py tests/test_tiny_realtime_chain.py tests/test_realtime_api.py tests/test_realtime_smoke.py -q
```

Expected: all pass.

- [ ] **Step 2: Run ESP source and asset suites**

```powershell
python -m pytest tests/test_tiny_esp_guards.py tests/test_esp_assets.py -q
```

Expected: all pass, including no `130/131`, presence of `140-144`, true pre-roll, 200 ms trailing silence, turn IDs, and end-state restoration.

- [ ] **Step 3: Run the complete existing test suite**

```powershell
python -m pytest -q
```

Expected: all tests pass without warnings attributable to the changes.

- [ ] **Step 4: Build ESP-IDF without touching local config**

Use the repository's documented ESP-IDF environment and run:

```powershell
idf.py -C esp_idf_demo build
```

Expected: successful build. Before and after build, verify `git diff -- esp_idf_demo/main/config.h` is identical to the user's pre-existing diff and `sdkconfig.multinet_eval` remains untracked/unmodified by the agent.

- [ ] **Step 5: Review the final diff and protected files**

```powershell
git status --short
git diff --check
git diff --stat
git diff --name-only
```

Expected: only planned source, test, script, and design/plan files plus the user's pre-existing protected changes. No generated build output or secrets are staged.

- [ ] **Step 6: Report deployment and commit recommendation**

Report test counts, build evidence, remaining hardware-only validation, exact cloud restart plan for port `18111`, and exact board build/flash/monitor commands. Mark `建议提交` only if all available automated checks and build pass; otherwise mark `暂不建议提交` with blockers. Do not commit, push, SSH-deploy, restart, flash, or monitor until the user explicitly authorizes the relevant action.
