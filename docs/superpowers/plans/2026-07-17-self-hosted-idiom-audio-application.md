# Self-hosted Idiom Audio Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved Qwen3-TTS 1.7B `clone_coffee_20s_v1` fixed-audio set at `0.9` tempo with 500 ms trailing silence, add 500 ms after every played idiom without rewriting the 29,493 source files, and remove DashScope TTS from active runtime and generation routes.

**Architecture:** Fixed prompts remain cloud-hosted WAV assets. Idiom source WAV files remain byte-for-byte unchanged; the merged response appends 16,000 bytes of PCM16 zero samples only when the final segment is `idioms/*`. Dynamic speech uses the self-hosted WebSocket service exclusively and appends one 500 ms post-roll after the complete reply, never after each streamed text segment.

**Tech Stack:** Python 3.11+, FastAPI, `websockets`, PCM16 16 kHz mono audio, ffmpeg `atempo`, pytest/unittest, ESP-IDF 5.5.4.

## Global Constraints

- Work only in `D:\20260709_Tiny_Machine_Robot-merge` on branch `merge`.
- Do not modify or commit `esp_idf_demo/main/config.h`, `esp_idf_demo/sdkconfig.multinet_eval`, local bundle files, KWS experiments, IP addresses, Wi-Fi credentials, or device IDs.
- ASR remains DashScope; this plan changes TTS only.
- Runtime and offline TTS must use `http://127.0.0.1:18122` / `ws://127.0.0.1:18122/tts/realtime`, model `qwen3-tts-base-1_7b`, voice `clone_coffee_20s_v1`.
- Do not fall back to DashScope TTS when self-hosted TTS is unavailable.
- Use tempo factor `0.9` and append exactly 500 ms of silence to newly generated fixed audio.
- Do not rewrite, time-stretch, fade, overlap, or otherwise edit any `data/static_audio/idioms/*` source file.
- Do not commit or push until the user explicitly says `可提交并推送`.

---

### Task 1: Enforce the approved 500 ms idiom response tail

**Files:**
- Modify: `src/providers/pcm_tail.py`
- Modify: `src/providers/static_audio.py`
- Modify: `tests/test_pcm_tail.py`
- Modify: `tests/test_voice_skills.py`

**Interfaces:**
- Produces: `PCM_POST_ROLL_MS = 500` and `pcm16_silence(duration_ms: int) -> bytes`.
- Produces: `merge_idiom_static_audio_plan(...)` which appends 500 ms only when the last segment ID starts with `idioms/`.

- [ ] Write failing tests asserting 500 ms fixed-tail padding and exact `fixed + idiom + 500ms-zero` merged bytes.
- [ ] Run `python -m pytest tests/test_pcm_tail.py tests/test_voice_skills.py -q` and confirm the new assertions fail because the current limit is 80 ms and idiom merge has no post-roll.
- [ ] Change the tail constant to 500 ms, add the zero-PCM helper, and append it once at the end of idiom-ending plans without inspecting or modifying the idiom file.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Make self-hosted TTS the only active dynamic provider

**Files:**
- Create: `src/providers/self_hosted_realtime_tts.py`
- Modify: `src/settings.py`
- Modify: `.env.example`
- Modify: `src/services/realtime_session.py`
- Modify: `src/workers/pipeline.py`
- Modify: `src/app.py`
- Create: `tests/test_self_hosted_realtime_tts.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_realtime_api.py`

**Interfaces:**
- Produces: `SelfHostedRealtimeTtsError`, `self_hosted_realtime_tts_health()`, `warmup_self_hosted_realtime_tts_session()`, `stream_self_hosted_realtime_tts_chunks()`, and `synthesize_self_hosted_audio()`.
- The streaming function emits self-hosted PCM chunks followed by exactly one 500 ms zero-PCM post-roll after all text segments.

- [ ] Write failing tests for health configuration, WebSocket payload voice selection, one final post-roll, no per-segment post-roll, one-shot WAV output, and runtime imports with no DashScope fallback.
- [ ] Run the focused provider/session/pipeline tests and confirm failures are caused by the missing provider and old imports.
- [ ] Implement the provider and settings defaults for `qwen3-tts-base-1_7b`, `clone_coffee_20s_v1`, and 500 ms.
- [ ] Route FastAPI health, realtime sessions, and the legacy task worker to self-hosted TTS; surface an explicit self-hosted error when unavailable.
- [ ] Re-run focused tests and confirm they pass.

### Task 3: Make fixed-audio generation self-hosted-only at 0.9 tempo

**Files:**
- Modify: `scripts/prepare_idiom_fixed_audio.py`
- Modify: `scripts/prebuild_idiom_static_audio.py`
- Modify: `tests/test_prepare_idiom_fixed_audio.py`
- Modify: `tests/test_prebuild_idiom_static_audio.py`

**Interfaces:**
- Fixed generator backend is exactly `self_hosted`.
- Manifest records provider `self_hosted`, model, voice, tempo factor `0.9`, and tail silence `500`.

- [ ] Write failing tests rejecting `http`/DashScope TTS backends and requiring the approved provider/model/voice/tempo/tail metadata.
- [ ] Run the two script test modules and confirm expected failures.
- [ ] Replace active DashScope synthesis selection with self-hosted PCM generation plus ffmpeg `atempo=0.9,apad=pad_dur=0.5`.
- [ ] Remove board prompt generation because the three prompts now stream from the cloud endpoint.
- [ ] Re-run the script tests and confirm they pass.

### Task 4: Validate and prepare the approved assets for production

**Files:**
- Modify: `docs/superpowers/summaries/2026-07-16-idiom-fixed-audio-tail-current-state.md`

**Interfaces:**
- Consumes the approved candidate directory `/tmp/idiom_self_hosted_fixed_09_500ms_20260717/output/cloud/idiom_game`.
- Produces a verified 14-file manifest and a reversible server-side backup/install command for later deployment.

- [ ] Verify all 14 WAV files are 16 kHz, mono, PCM16, have at least 500 ms zero tail, and match the approved candidate hashes.
- [ ] Verify the opening preview is strict PCM concatenation and idiom source files remain unchanged.
- [ ] Run focused tests, then the complete Python suite while reporting the pre-existing Volcengine assertion separately.
- [ ] Run ESP static tests and an ESP-IDF 5.5.4 build because board cloud-prompt changes are in the same uncommitted change set.
- [ ] Review `git diff`, confirm protected local files are excluded, and recommend whether the change is ready to commit without committing it.
