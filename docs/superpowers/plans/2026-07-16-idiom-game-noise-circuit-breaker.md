# Idiom Game Noise Circuit Breaker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为四种成语游戏模式实现统一的 25 秒 presence 提醒、20 秒提醒后退出、首次非有效轮次提示、30 秒重试空闲退出和不可被噪声刷新的 60 秒硬退出。

**Architecture:** 云端从现有成语 trace 导出可选 `turn_outcome` 并随持久游戏 WebSocket 的 `done` 下发；板端解析该字段，用一个软 idle deadline 和一个 noise hard deadline 管理正常、presence 与 retry 三个阶段。空 ASR 继续走现有 recoverable error，不增加 ASR/LLM/TTS 请求；新提示音仅在开发阶段生成并固化到 SPIFFS。

**Tech Stack:** Python 3.11, FastAPI, WebSocket, unittest/pytest, ESP-IDF 5.5.4, C, cJSON, SPIFFS, DashScope realtime TTS（仅预生成素材）

## Global Constraints

- 只在 `D:\20260709_Tiny_Machine_Robot-merge` 的 `merge` 分支工作，不修改 0701 仓库。
- 不修改、不暂存、不提交 `esp_idf_demo/main/config.h`。
- 不暂存或提交 `esp_idf_demo/sdkconfig.multinet_eval` 和本地部署 bundle。
- DashScope 仍是预期 ASR provider；旧 Volcengine 默认值断言作为既有失败单独记录。
- 成语模式运行时禁止动态 TTS；新 PCM 必须是 16kHz、单声道、16-bit little-endian。
- 普通咖啡单轮 realtime 链路不得增加 `turn_outcome` 或改变关闭行为。
- 所有状态继续按连接的 `X-Device-ID` 隔离，`done` 必须匹配 active `turn_id`。
- 实施过程中不执行 git commit/push；每个提交检查点只汇报建议，等待用户明确“可提交并推送”。

---

### Task 1: 云端导出成语轮次结果

**Files:**
- Modify: `src/voice_skills/router.py`
- Modify: `src/services/realtime_session.py`
- Test: `tests/test_voice_skills.py`

**Interfaces:**
- Produces: `SkillResult.turn_outcome: str | None`
- Produces: session trace key `turn_outcome`
- Allowed idiom values: `meaningful`, `invalid`, `off_topic`, `exit`

- [ ] **Step 1: Write failing router outcome tests**

Extend existing `SkillRouter` tests so returned results assert these mappings:

```python
assert router.route(device_id="dev-1", text="开始成语接龙").turn_outcome == "meaningful"
assert router.route(device_id="dev-1", text="重复一下").turn_outcome == "meaningful"
assert router.route(device_id="dev-1", text="简单一点").turn_outcome == "meaningful"
assert router.route(device_id="dev-1", text="退出游戏").turn_outcome == "exit"
```

Use the existing deterministic idiom fixtures for successful reply, wrong prefix, repeated word and unknown idiom, and assert:

```python
assert valid_result.turn_outcome == "meaningful"
assert wrong_prefix_result.turn_outcome == "invalid"
assert repeated_result.turn_outcome == "invalid"
assert unknown_result.turn_outcome == "invalid"
assert off_topic_result.turn_outcome == "off_topic"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_voice_skills.py -q
```

Expected: failures because `SkillResult` has no `turn_outcome` field.

- [ ] **Step 3: Implement one deterministic mapping helper**

Add the optional dataclass field and a private mapping helper in `router.py`:

```python
@dataclass
class SkillResult:
    # existing fields...
    turn_outcome: str | None = None


def _idiom_turn_outcome(trace: dict, *, end_skill_state: bool) -> str:
    if end_skill_state:
        return "exit"
    event = str(trace.get("idiom_event") or "")
    if event in {"start", "robot_reply", "repeat", "difficulty_switch"}:
        return "meaningful"
    if event == "off_topic":
        return "off_topic"
    return "invalid"
```

Have `_text_result()` set this field only for `skill_name == "idiom_game"`. Do not call the LLM from this helper and do not accept `matches_expected_pinyin` as an outcome authority.

- [ ] **Step 4: Persist the outcome into trace**

In `run_realtime_session()`, after a skill result is returned:

```python
if skill_result.turn_outcome is not None:
    updated["trace"]["turn_outcome"] = skill_result.turn_outcome
```

Do not set this trace key for non-idiom results.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_voice_skills.py -q
```

Expected: all voice skill tests pass.

- [ ] **Step 6: Submission checkpoint**

Review only these paths and recommend whether they are ready; do not commit:

```powershell
git diff -- src/voice_skills/router.py src/services/realtime_session.py tests/test_voice_skills.py
```

---

### Task 2: 在持久游戏 done 中下发 turn_outcome

**Files:**
- Modify: `src/api/realtime.py`
- Test: `tests/test_opus_uplink.py`
- Test: `tests/test_realtime_api.py`

**Interfaces:**
- Consumes: session trace `turn_outcome`
- Produces: optional WebSocket JSON field `done.turn_outcome`

- [ ] **Step 1: Write failing protocol tests**

Add/extend tests around `_wait_for_skill_metadata()` and persistent idiom WebSocket:

```python
metadata = await _wait_for_skill_metadata(
    "session-1",
    default_skill_name="idiom_game",
    timeout_seconds=0.1,
)
assert metadata["turn_outcome"] == "meaningful"
```

Populate the fake session trace with:

```python
{
    "skill_route_complete": True,
    "skill_name": "idiom_game",
    "skill_active": True,
    "end_skill_state": False,
    "turn_outcome": "meaningful",
}
```

Extend the two-turn persistent WebSocket test so each matching `done` carries the expected outcome while the connection remains open. Add an ordinary coffee `done` assertion:

```python
assert "turn_outcome" not in ordinary_done
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_opus_uplink.py tests/test_realtime_api.py -q
```

Expected: new outcome assertions fail because metadata and board payload filtering do not expose it.

- [ ] **Step 3: Extend metadata and board payload filtering**

In `_wait_for_skill_metadata()` return `turn_outcome` only when trace contains one of:

```python
IDIOM_TURN_OUTCOMES = {"meaningful", "invalid", "off_topic", "exit"}
```

In `_make_board_done_payload()`, add `turn_outcome` to the allow-list. Because ordinary sessions never set the key, their JSON remains unchanged.

- [ ] **Step 4: Verify the persistent adapter forwards the field**

Keep `_IdiomTurnWebSocket.send_json()` behavior:

```python
forwarded.update(await _wait_for_skill_metadata(...))
forwarded["turn_id"] = self.turn_id
```

Do not close the outer WebSocket after `done` and do not add the outcome to recoverable `error` messages.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_opus_uplink.py tests/test_realtime_api.py -q
```

Expected: protocol tests pass, including two turns on one WebSocket and absence from ordinary coffee payloads.

- [ ] **Step 6: Submission checkpoint**

Review only the cloud protocol diff; do not commit.

---

### Task 3: 板端解析可选 outcome 并保持兼容

**Files:**
- Modify: `esp_idf_demo/main/cloud_client.h`
- Modify: `esp_idf_demo/main/cloud_client.c`
- Test: `tests/test_tiny_esp_guards.py`

**Interfaces:**
- Consumes: optional JSON `turn_outcome`
- Produces: `cloud_realtime_session_t.turn_outcome[16]`

- [ ] **Step 1: Write failing ESP protocol guards**

Add assertions that the session struct contains the field and the WebSocket `done` branch copies it with bounded optional parsing:

```python
assert "char turn_outcome[16];" in cloud_header
assert '"turn_outcome"' in cloud_source
assert "session.turn_outcome" in cloud_source
```

- [ ] **Step 2: Run the guard and verify RED**

Run:

```powershell
python -m pytest tests/test_tiny_esp_guards.py -q
```

Expected: new parser assertions fail.

- [ ] **Step 3: Add bounded optional parsing**

Extend `cloud_realtime_session_t`:

```c
char turn_outcome[16];
```

In the persistent WebSocket `done` branch call:

```c
cloud_opus_uplink_copy_optional_string(root,
                                       "turn_outcome",
                                       uplink->session.turn_outcome,
                                       sizeof(uplink->session.turn_outcome));
```

Missing fields must leave an empty string for legacy compatibility. Do not reject the entire `done` because of a missing outcome.

- [ ] **Step 4: Run the guard and verify GREEN**

Run:

```powershell
python -m pytest tests/test_tiny_esp_guards.py -q
```

Expected: all ESP source guards pass.

---

### Task 4: 增加“我没听清”本地静态音频

**Files:**
- Create: `esp_idf_demo/spiffs/idiom_game_misheard_1.pcm`
- Modify: `esp_idf_demo/spiffs_prompt_manifest.json`
- Modify: `tests/test_esp_assets.py`

**Interfaces:**
- Produces: `/spiffs/idiom_game_misheard_1.pcm`
- Exact text: `我没听清，你再说一次。`
- Format: PCM16LE, 16000 Hz, mono, at most 64 KiB

- [ ] **Step 1: Write failing asset tests**

Extend `test_idiom_game_prompt_audio_assets_are_pcm16_resources()` to include the new file, and extend the exact manifest mapping:

```python
"idiom_game_misheard_1.pcm": "我没听清，你再说一次。",
```

- [ ] **Step 2: Run asset tests and verify RED**

Run:

```powershell
python -m pytest tests/test_esp_assets.py::EspAssetTests::test_idiom_game_prompt_audio_assets_are_pcm16_resources tests/test_esp_assets.py::EspAssetTests::test_local_prompt_manifest_preserves_original_prompt_text -q
```

Expected: missing file and manifest entry failures.

- [ ] **Step 3: Generate once on the configured cloud server**

On the server, use the configured realtime provider so its existing normalization returns PCM16LE 16 kHz mono:

```bash
cd /home/intern2/projects/20260709_Tiny_Machine_Robot
.venv/bin/python - <<'PY'
from pathlib import Path
from src.providers.realtime_tts import stream_realtime_tts

target = Path("/tmp/idiom_game_misheard_1.pcm")
pcm = b"".join(stream_realtime_tts("我没听清，你再说一次。"))
assert pcm and len(pcm) % 2 == 0 and len(pcm) <= 64 * 1024
target.write_bytes(pcm)
print(target, len(pcm))
PY
```

Copy only that generated PCM back to `esp_idf_demo/spiffs/`; never copy `.env`, API keys, IPs or device IDs into the repository.

- [ ] **Step 4: Update and validate the manifest**

Add the exact prompt mapping while preserving `generator` and `audio_format`. Run the focused tests and verify they pass.

---

### Task 5: 实现 25/20/30/60 秒状态机和噪声熔断

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Test: `tests/test_tiny_esp_guards.py`
- Test: `tests/test_esp_assets.py`

**Interfaces:**
- Consumes: `cloud_realtime_session_t.turn_outcome`
- Consumes: existing empty-ASR recoverable error codes
- Produces: `idle_exit` reasons `no_vad_after_presence_prompt`, `no_vad_after_nonmeaningful_turn`, `repeated_nonmeaningful_hard_timeout`

- [ ] **Step 1: Replace old guard expectations with failing policy tests**

Assert exact constants:

```python
assert "#define APP_IDIOM_GAME_NORMAL_IDLE_MS 25000" in main
assert "#define APP_IDIOM_GAME_POST_PRESENCE_IDLE_MS 20000" in main
assert "#define APP_IDIOM_GAME_POST_NONMEANINGFUL_IDLE_MS 30000" in main
assert "#define APP_IDIOM_GAME_NOISE_HARD_IDLE_MS 60000" in main
assert "APP_IDIOM_GAME_HARD_IDLE_MS 180000" not in main
```

Add source guards for:

```text
nonmeaningful_prompted
noise_hard_deadline_us
turn_outcome == meaningful/invalid/off_topic/exit
idiom_game_misheard_1.pcm
action=nonmeaningful_prompt_suppressed
```

Check that hard deadline assignment is guarded by `noise_hard_deadline_us == 0` and that repeated nonmeaningful branches do not assign a new 60-second deadline.

- [ ] **Step 2: Run guards and verify RED**

Run:

```powershell
python -m pytest tests/test_tiny_esp_guards.py tests/test_esp_assets.py -q
```

Expected: old constants and absent circuit-breaker state cause failures.

- [ ] **Step 3: Add explicit policy helpers in main.c**

Add bounded string helpers with these semantics:

```c
static bool app_idiom_game_outcome_is_missing(const char *value);
static bool app_idiom_game_outcome_is_meaningful(const char *value);
static bool app_idiom_game_outcome_is_nonmeaningful(const char *value);
static bool app_idiom_game_outcome_is_exit(const char *value);
```

An empty value uses legacy meaningful behavior. `invalid`, `off_topic`, and unknown non-empty values are nonmeaningful. `exit` is handled before playback suppression.

- [ ] **Step 4: Implement normal silence presence transition**

Initialize normal idle to 25 seconds and noise hard to zero. On an idle VAD wait timeout:

```text
noise hard expired -> final idle exit
normal 25s expired and no presence/nonmeaningful prompt -> play presence, arm 20s
presence 20s expired -> final idle exit
retry 30s expired -> final idle exit
otherwise -> continue VAD wait
```

All local prompt playback must set playback state, disable upload, and request the existing 200 ms echo guard before rearming.

- [ ] **Step 5: Implement first empty and repeated-empty behavior**

For `empty_decoded_audio`, `asr_empty_text`, and `asr_no_final_text`:

```text
first nonmeaningful -> play misheard once, latch, anchor hard at speech_detected+60s
repeated nonmeaningful -> no audio playback, keep original hard anchor
both -> rearm retry idle for30s after current turn handling
```

Retain the existing 1.5-second earliest-prompt floor for the first misheard prompt.

- [ ] **Step 6: Implement successful done behavior**

Before downloading response audio:

```text
exit/end_skill -> play required final audio and exit
meaningful/missing legacy -> play audio, clear both prompt flags, clear noise hard, arm25s
first invalid/off_topic -> play static server response once, latch, anchor60s, arm30s
repeated invalid/off_topic -> skip audio stream, keep hard anchor, arm30s
```

For a local MultiNet repeat or mode command, use the known local command kind as meaningful, play its static session audio and clear the circuit breaker.

- [ ] **Step 7: Preserve deadline and error isolation**

Before entering an active VAD turn, retain the previous absolute soft deadline. Recoverable infrastructure errors restore that prior deadline instead of granting a fresh 25/20/30 seconds. Stale `turn_id`, idle binary and protocol errors do not touch either deadline.

- [ ] **Step 8: Run focused tests and ESP build**

Run:

```powershell
python -m pytest tests/test_tiny_esp_guards.py tests/test_esp_assets.py -q
cd esp_idf_demo
idf.py build
```

Expected: Python tests pass and ESP-IDF 5.5.4 build exits 0 with application and SPIFFS images generated.

---

### Task 6: 全量回归、报告与提交建议

**Files:**
- Modify: `docs/superpowers/summaries/2026-07-15-idiom-game-idle-exit-current-state.md`
- Create: `docs/superpowers/summaries/2026-07-16-idiom-game-noise-circuit-breaker-current-state.md`

**Interfaces:**
- Produces: verification evidence and deployment/flash handoff

- [ ] **Step 1: Run focused cloud and ESP tests**

```powershell
python -m pytest tests/test_voice_skills.py tests/test_opus_uplink.py tests/test_realtime_api.py tests/test_tiny_esp_guards.py tests/test_esp_assets.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the complete repository suite**

```powershell
python -m pytest -q
```

Expected: only the explicitly accepted stale Volcengine-default assertion may fail; record its exact node id and ensure every other test passes. Then rerun with only that exact node deselected and require exit 0. Do not hide or broadly filter other failures.

- [ ] **Step 3: Run final ESP-IDF build and diff checks**

```powershell
cd D:\20260709_Tiny_Machine_Robot-merge\esp_idf_demo
idf.py build
cd ..
git diff --check
git status --short
```

Expected: build and diff check exit 0; status contains protected local files plus only intentional feature paths.

- [ ] **Step 4: Write the current-state report**

Record exact constants, transition table, VAD thresholds, first/repeated nonmeaningful behavior, `turn_outcome` mapping, test counts, binary size and deployment order. Explicitly state that runtime idiom TTS remains disabled.

- [ ] **Step 5: Review protected files and recommend submission**

Use an explicit `git diff --name-only` and recommend whether to submit. Never stage `config.h`, `sdkconfig.multinet_eval`, or the bundle. Wait for the user's “可提交并推送” before any commit or push.
