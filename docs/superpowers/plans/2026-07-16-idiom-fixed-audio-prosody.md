# Idiom Fixed Audio Prosody Implementation Plan

> **Superseded:** The approved 2026-07-17 implementation uses self-hosted Qwen3-TTS 1.7B, `clone_coffee_20s_v1`, tempo `0.9`, a 500 ms tail, and cloud-hosted fixed prompts. DashScope/80 ms/96 KiB board steps below are historical only.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate slower, naturally completed idiom fixed prompts and verify the opening as a real fixed-prefix-to-idiom concatenation before production installation.

**Architecture:** Add optional per-call realtime TTS prosody controls with unchanged defaults, extend the fixed candidate tool with subset batches and manifest-recorded synthesis text/parameters, and give only idiom-game local prompts a 96KiB streamed playback cap. Generate three temporary audition batches at rates 0.82, 0.85, and 0.90; do not install a final batch until the user chooses one.

**Tech Stack:** Python 3.11, DashScope Qwen realtime TTS SDK, PCM16LE/WAV, pytest, ESP-IDF 5.5.4.

## Global Constraints

- Work only in `D:\20260709_Tiny_Machine_Robot-merge` on branch `merge`.
- Do not modify or stage `esp_idf_demo/main/config.h`, `esp_idf_demo/sdkconfig.multinet_eval`, or bundle files.
- Do not modify `esp_idf_demo/main/audio_out.c`.
- Do not analyze, alter, regenerate, trim, fade, or overlap `idioms/*` audio.
- Runtime TTS callers that omit prosody overrides must retain current behavior.
- Keep all outputs 16kHz, mono, signed PCM16LE with at least 80ms safe quiet tail.
- Only the three idiom-game local prompts may use the 96KiB cap; other board prompts remain capped at 64KiB.
- No commit, push, production install, server restart, or flash without explicit user authorization.

---

### Task 1: Optional Realtime TTS Prosody Controls

**Files:**
- Modify: `src/providers/realtime_tts.py`
- Modify: `scripts/prebuild_idiom_static_audio.py`
- Test: `tests/test_realtime_tts_provider.py`
- Test: `tests/test_prebuild_idiom_static_audio.py`

**Interfaces:**
- Produces: `warmup_realtime_tts_session(*, speech_rate: float | None = None, instructions: str | None = None)`.
- Produces: optional keyword-only `speech_rate` and `instructions` arguments on `stream_realtime_tts_chunks()`.
- Consumes: optional `speech_rate` and `instructions` keys in the fixed synthesizer context.

- [ ] Write tests asserting explicit values reach `client.update_session()` and omitted values are absent.
- [ ] Run the focused tests and verify they fail against the current signatures.
- [ ] Implement optional parameters without changing default runtime calls.
- [ ] Make `synthesize_realtime_wav()` forward context overrides.
- [ ] Run the focused tests and verify they pass.

### Task 2: Audition Subsets, Synthesis Text, and Manifest Parameters

**Files:**
- Modify: `scripts/prepare_idiom_fixed_audio.py`
- Modify: `tests/test_prepare_idiom_fixed_audio.py`

**Interfaces:**
- Produces: `FIXED_TTS_INSTRUCTIONS` and `SYNTHESIS_TEXT_OVERRIDES`.
- Produces: optional exact `segment_ids` filtering in `generate_candidate_batch()`.
- Records: `display_text`, `synthesis_text`, `speech_rate`, and `instructions` in every manifest entry.

- [ ] Write failing tests for start display colon versus synthesis comma, exact subset generation, forbidden unknown/idiom/pinyin segments, and manifest prosody metadata.
- [ ] Run the focused tests and verify failure.
- [ ] Implement exact known-segment subset selection; reject empty or unknown selections.
- [ ] Pass synthesis text and prosody metadata to the synthesizer.
- [ ] Update validation so a partial audition manifest validates only its explicit requested set; full install-cloud still requires all cloud entries and install-board still requires all three board entries.
- [ ] Run focused tests and verify pass.

### Task 3: Idiom-Only 96KiB Stream Limit

**Files:**
- Modify: `esp_idf_demo/main/main.c`
- Modify: `scripts/prepare_idiom_fixed_audio.py`
- Modify: `tests/test_esp_assets.py`
- Modify: `tests/test_tiny_esp_guards.py`
- Modify: `tests/test_prepare_idiom_fixed_audio.py`

**Interfaces:**
- Produces: `APP_IDIOM_GAME_PROMPT_MAX_BYTES (96 * 1024)` in `main.c`.
- Changes: `app_play_retry_prompt(reason, path, max_bytes)` so ordinary callers retain 64KiB and idiom callers pass 96KiB.
- Changes: fixed candidate board maximum to 96KiB.

- [ ] Write failing ESP source/asset and candidate-limit tests.
- [ ] Run focused tests and verify failure.
- [ ] Implement the separate streamed playback limit without editing `audio_out.c` or `config.h`.
- [ ] Run focused tests and verify pass.

### Task 4: Generate Three Audition Batches

**Files:**
- Create outside repository: `%TEMP%\idiom_fixed_prosody_20260716\rate_082`, `rate_085`, and `rate_090`.
- Update: `docs/superpowers/summaries/2026-07-16-idiom-fixed-audio-tail-current-state.md`.

**Interfaces:**
- Consumes: exact subset `idiom_game/start` plus three board prompts.
- Produces: four validated candidates and one `start + idiom` preview per rate.

- [ ] Upload only the required modified generator/provider files to a remote `/tmp` code directory.
- [ ] Generate the three four-entry batches with rates 0.82, 0.85, and 0.90 using the approved instruction.
- [ ] Validate every remote batch and transfer it to the matching local temporary directory.
- [ ] Revalidate every local batch and compare manifest hashes.
- [ ] Create WAV previews for the board PCM files.
- [ ] Create a strict `start_pcm + unchanged representative_idiom_pcm` WAV preview for each rate.
- [ ] Record model, voice, rate, durations, sizes, tail reports, hashes, and preview paths in the current-state report.
- [ ] Stop for user listening approval; do not overwrite the current board files or cloud production files yet.

### Task 5: Verification and Handoff

**Files:**
- Update: `docs/superpowers/summaries/2026-07-16-idiom-fixed-audio-tail-current-state.md`

**Interfaces:**
- Produces: fresh test/build evidence and a safe pending diff.

- [ ] Run fixed-audio, realtime TTS, voice skill, realtime API, ESP asset, and ESP guard focused tests while deselecting only the documented stale Volcengine assertion.
- [ ] Run the complete filtered suite and record any other failure.
- [ ] Build with ESP-IDF 5.5.4.
- [ ] Run `git diff --check`, verify no staged files, and verify no `idioms/*` changes.
- [ ] Report that human listening remains the acceptance gate and provide a commit recommendation without committing.
