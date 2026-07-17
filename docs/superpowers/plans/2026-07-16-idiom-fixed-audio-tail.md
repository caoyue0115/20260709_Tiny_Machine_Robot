# Idiom Fixed Audio Tail Implementation Plan

> **Superseded:** The approved 2026-07-17 implementation uses self-hosted Qwen3-TTS 1.7B, `clone_coffee_20s_v1`, tempo `0.9`, a 500 ms tail, and cloud-hosted fixed prompts. DashScope/80 ms/board-install steps below are historical only.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every runtime idiom-game fixed sentence finishes naturally and every fixed-to-next-segment boundary is strictly sequential, without inspecting or modifying any `idioms/*` audio.

**Architecture:** Add a small PCM16 tail-quality module shared by startup validation, candidate preparation, and tests. Reuse `idiom_game/start` as the complete opening prefix, validate only runtime fixed segments, merge fixed audio sequentially with a verified 80ms quiet tail, and generate fixed WAV/board PCM candidates offline through the existing DashScope realtime TTS configuration.

**Tech Stack:** Python 3.11, FastAPI realtime sessions, DashScope/Qwen realtime TTS for one-time generation, WAV/PCM16LE at 16kHz mono, pytest, ESP-IDF 5.5.4 SPIFFS assets.

## Global Constraints

- Work only in `D:\20260709_Tiny_Machine_Robot-merge` on branch `merge`.
- Do not modify or stage `esp_idf_demo/main/config.h`, `esp_idf_demo/sdkconfig.multinet_eval`, or local bundle files.
- Do not add tail/RMS/silence quality analysis, rewrite, trim, or regenerate any `data/static_audio/idioms/*` file; preserve the existing existence/format validation and normal playback reads.
- Do not modify `esp_idf_demo/main/audio_out.c` or its codec/jitter close behavior.
- Do not introduce runtime dynamic TTS; DashScope is used only to prepare static candidates.
- Keep all output at `16000Hz / mono / signed PCM16 little-endian`.
- Use one shared threshold set: 10ms quiet-window RMS `<= 100`, source last-20ms RMS `<= 100`, final sample absolute value `<= 100`, safe quiet tail `>= 80ms`.
- Keep every board prompt file even-sized and `<= 65536` bytes.
- Keep `robot_first`, `turn_prompt`, `robot_reply`, and `pinyin/*` assets on disk; only stop normal opening references to `robot_first`.
- Keep DashScope as the intended ASR provider and report the stale Volcengine assertion separately.
- Do not stage, commit, push, deploy, or flash until the user explicitly authorizes the relevant action.

---

### Task 1: PCM16 Tail Quality Primitive

**Files:**
- Create: `src/providers/pcm_tail.py`
- Create: `tests/test_pcm_tail.py`

**Interfaces:**
- Consumes: raw 16kHz mono PCM16LE bytes.
- Produces: `PcmTailReport`, `analyze_pcm16_tail(pcm: bytes) -> PcmTailReport`, and `ensure_safe_pcm16_tail(pcm: bytes) -> bytes`.

- [ ] **Step 1: Write failing tests for source completeness and safe-tail padding**

```python
from array import array

import pytest

from src.providers.pcm_tail import (
    PcmTailError,
    analyze_pcm16_tail,
    ensure_safe_pcm16_tail,
)


def _pcm(samples: list[int]) -> bytes:
    return array("h", samples).tobytes()


def test_rejects_audible_endpoint_instead_of_hiding_it_with_zero_padding() -> None:
    audible_tail = _pcm([0] * 1600 + [1200] * 320)
    report = analyze_pcm16_tail(audible_tail)
    assert report.source_complete is False
    with pytest.raises(PcmTailError, match="fixed_audio_source_tail_incomplete"):
        ensure_safe_pcm16_tail(audible_tail)


def test_pads_only_a_complete_source_to_eighty_ms() -> None:
    complete_short_tail = _pcm([800] * 1600 + [0] * 320)
    padded = ensure_safe_pcm16_tail(complete_short_tail)
    report = analyze_pcm16_tail(padded)
    assert report.source_complete is True
    assert report.safe_tail is True
    assert report.quiet_tail_ms >= 80
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pcm_tail.py -q
```

Expected: collection fails because `src.providers.pcm_tail` does not exist.

- [ ] **Step 3: Implement the shared PCM tail analyzer**

Implement these exact public names in `src/providers/pcm_tail.py`:

```python
from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import sys

PCM_SAMPLE_RATE = 16000
PCM_SAMPLE_WIDTH_BYTES = 2
QUIET_WINDOW_MS = 10
SOURCE_TAIL_MS = 20
SAFE_TAIL_MS = 80
QUIET_RMS_THRESHOLD = 100.0
LAST_SAMPLE_ABS_THRESHOLD = 100


class PcmTailError(ValueError):
    pass


@dataclass(frozen=True)
class PcmTailReport:
    last_20ms_rms: float
    last_sample_abs: int
    quiet_tail_ms: int
    source_complete: bool
    safe_tail: bool


def _samples_from_pcm16le(pcm: bytes) -> array:
    if not pcm or len(pcm) % PCM_SAMPLE_WIDTH_BYTES:
        raise PcmTailError("invalid_pcm16_length")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _rms(samples: array) -> float:
    return math.sqrt(sum(int(value) * int(value) for value in samples) / len(samples))


def analyze_pcm16_tail(pcm: bytes) -> PcmTailReport:
    samples = _samples_from_pcm16le(pcm)
    window_samples = PCM_SAMPLE_RATE * QUIET_WINDOW_MS // 1000
    source_samples = PCM_SAMPLE_RATE * SOURCE_TAIL_MS // 1000
    source_tail = samples[-min(len(samples), source_samples):]
    source_rms = _rms(source_tail)
    quiet_windows = 0
    end = len(samples)
    while end >= window_samples:
        start = end - window_samples
        if _rms(samples[start:end]) > QUIET_RMS_THRESHOLD:
            break
        quiet_windows += 1
        end = start
    quiet_tail_ms = quiet_windows * QUIET_WINDOW_MS
    last_sample_abs = abs(int(samples[-1]))
    source_complete = (
        source_rms <= QUIET_RMS_THRESHOLD
        and last_sample_abs <= LAST_SAMPLE_ABS_THRESHOLD
    )
    return PcmTailReport(
        last_20ms_rms=source_rms,
        last_sample_abs=last_sample_abs,
        quiet_tail_ms=quiet_tail_ms,
        source_complete=source_complete,
        safe_tail=source_complete and quiet_tail_ms >= SAFE_TAIL_MS,
    )


def ensure_safe_pcm16_tail(pcm: bytes) -> bytes:
    report = analyze_pcm16_tail(pcm)
    if not report.source_complete:
        raise PcmTailError("fixed_audio_source_tail_incomplete")
    missing_ms = max(0, SAFE_TAIL_MS - report.quiet_tail_ms)
    missing_samples = PCM_SAMPLE_RATE * missing_ms // 1000
    return pcm + (b"\x00\x00" * missing_samples)
```

- [ ] **Step 4: Add edge tests**

Cover empty/odd PCM, exact80ms, no modification when already safe, negative samples, and final-sample failure with low average RMS.

- [ ] **Step 5: Run Task 1 tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_pcm_tail.py -q
```

Expected: all tests pass.

---

### Task 2: Complete Opening Prefix and Fixed-Segment Startup Gate

**Files:**
- Modify: `scripts/prebuild_idiom_static_audio.py`
- Modify: `src/voice_skills/idiom_game.py`
- Modify: `src/voice_skills/idiom_audio.py`
- Modify: `src/providers/static_audio.py`
- Modify: `tests/test_idiom_audio_catalog.py`
- Modify: `tests/test_voice_skills.py`

**Interfaces:**
- Consumes: `analyze_pcm16_tail()` from Task 1 and resolved WAV/PCM paths.
- Produces: `validate_fixed_audio_tail(segment_id: str, root: Path | None = None) -> Path` and the two-segment opening plan.

- [ ] **Step 1: Write failing opening-plan tests**

Update the expected start plan to:

```python
assert build_idiom_audio_plan(
    "好呀，我们玩成语接龙。小机仔先来：画龙点睛。",
    {"idiom_event": "start", "idiom_robot_reply_word": "画龙点睛"},
) == ["idiom_game/start", "idioms/画龙点睛"]
```

Add a source assertion that normal and regex-compat opening paths do not include `idiom_game/robot_first`.

- [ ] **Step 2: Write failing catalog-tail tests**

Create a valid16k WAV fixture ending in80ms zeros and a bad fixture ending in20ms of value1200. Require `build_idiom_audio_catalog()` to place a bad runtime fixed segment in `invalid_fixed_segments`, while a bad `static_error` raises `StaticAudioError`.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_voice_skills.py tests/test_idiom_audio_catalog.py -q
```

Expected: opening plan still has three segments and fixed tail is not validated.

- [ ] **Step 4: Reuse `idiom_game/start` as the complete prefix**

Change only the existing phrase definition:

```python
("idiom_game/start", "好呀，我们玩成语接龙。小机仔先来："),
```

Change both start branches in `build_idiom_audio_plan()` to:

```python
return ["idiom_game/start", f"idioms/{robot_word}"]
```

and:

```python
return ["idiom_game/start", f"idioms/{start_match.group('word')}"]
```

Do not delete the `robot_first` file or segment definition.

- [ ] **Step 5: Add fixed-tail validation without touching idioms**

In `src/providers/static_audio.py`, expose decoded PCM and validation:

```python
def read_static_audio_pcm(path: Path) -> bytes:
    return _read_audio_file(path)


def validate_fixed_audio_tail(segment_id: str, root: Path | None = None) -> Path:
    path = validate_static_audio_segment(segment_id, root=root)
    report = analyze_pcm16_tail(read_static_audio_pcm(path))
    if not report.safe_tail:
        raise StaticAudioError(f"static_audio_unsafe_tail:{segment_id}")
    return path
```

In `src/voice_skills/idiom_audio.py`, define exactly the runtime tail-gated set:

```python
TAIL_VALIDATED_FIXED_SEGMENTS = frozenset({
    "idiom_game/start",
    "idiom_game/robot_no_reply_user_win",
    "idiom_game/challenge_win",
    "idiom_game/mode_easy",
    "idiom_game/mode_normal",
    "idiom_game/mode_hard",
    "idiom_game/mode_full",
    "idiom_game/exit",
    "idiom_game/continue_prompt",
    "idiom_game/retry",
    "idiom_game/not_found",
    STATIC_ERROR_SEGMENT,
})
```

Validate only this set with `validate_fixed_audio_tail()`. Continue format/existence validation for legacy required fixed segments. Do not call tail analysis for segment IDs beginning with `idioms/`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_voice_skills.py tests/test_idiom_audio_catalog.py -q
```

Expected: all focused tests pass.

---

### Task 3: Sequential Idiom Static Merge

**Files:**
- Modify: `src/providers/static_audio.py`
- Modify: `src/services/realtime_session.py`
- Modify: `tests/test_voice_skills.py`
- Modify: `tests/test_realtime_api.py`

**Interfaces:**
- Consumes: parallel `segment_ids: Iterable[str]` and `paths: Iterable[Path]`.
- Produces: `merge_idiom_static_audio_plan(segment_ids: Iterable[str], paths: Iterable[Path]) -> bytes`.

- [ ] **Step 1: Write a failing no-overlap boundary test**

Use a fixed WAV whose PCM is `speech + 80ms zero` and an idiom WAV containing a recognizable marker. Assert:

```python
merged = merge_idiom_static_audio_plan(
    ["idiom_game/start", "idioms/画龙点睛"],
    [fixed_path, idiom_path],
)
assert merged == fixed_pcm + idiom_pcm
assert merged[len(fixed_pcm) - 2560 : len(fixed_pcm)] == b"\x00" * 2560
assert merged[len(fixed_pcm) :] == idiom_pcm
```

Add a second test proving the idiom bytes are returned unchanged and `analyze_pcm16_tail()` is never invoked for the idiom segment.

- [ ] **Step 2: Run the merge test and verify RED**

Expected: import fails because `merge_idiom_static_audio_plan` does not exist.

- [ ] **Step 3: Implement strict sequential merge**

```python
def merge_idiom_static_audio_plan(
    segment_ids: Iterable[str],
    paths: Iterable[Path],
) -> bytes:
    ids = [str(item) for item in segment_ids]
    resolved = list(paths)
    if len(ids) != len(resolved):
        raise StaticAudioError("static_audio_plan_length_mismatch")
    merged = bytearray()
    for segment_id, path in zip(ids, resolved, strict=True):
        pcm = read_static_audio_pcm(path)
        if segment_id.startswith("idiom_game/"):
            report = analyze_pcm16_tail(pcm)
            if not report.safe_tail:
                raise StaticAudioError(f"static_audio_unsafe_tail:{segment_id}")
        merged.extend(pcm)
    return bytes(merged)
```

This function must never trim, fade, overlap, or inspect an `idioms/*` PCM payload.

- [ ] **Step 4: Route idiom sessions through the strict merger**

Track the resolved plan IDs, including `idiom_game/static_error` fallback. In `start_realtime_session_from_question()`, use the strict merger only when `skill_result.skill_name == "idiom_game"`; retain `merge_static_audio_paths()` for any other future static-audio consumer.

- [ ] **Step 5: Run focused realtime tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_voice_skills.py tests/test_realtime_api.py -q
```

Expected: all focused tests pass and streamed bytes retain exact segment order.

---

### Task 4: Fixed Candidate Preparation Tool

**Files:**
- Create: `scripts/prepare_idiom_fixed_audio.py`
- Create: `tests/test_prepare_idiom_fixed_audio.py`
- Modify: `scripts/prebuild_idiom_static_audio.py`

**Interfaces:**
- Consumes: an explicit fixed-only inventory plus an injected synthesizer in tests or the existing DashScope realtime synthesizer in CLI generation mode.
- Produces: validated/padded cloud WAV files, three board PCM files, and a JSON manifest with SHA-256.

- [ ] **Step 1: Write failing processor tests with an injected synthesizer**

Cover these exact cases:

```text
complete source + short quiet tail -> output padded to80ms
audible final20ms -> generation rejected and previous output untouched
board output >65536 bytes -> rejected
manifest records text/model/voice/bytes/sha256
the source list contains no idioms/* entry
start text is the complete opening prefix
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest tests/test_prepare_idiom_fixed_audio.py -q
```

Expected: script module does not exist.

- [ ] **Step 3: Implement the fixed-only candidate inventory**

Define `CLOUD_FIXED_TEXTS` explicitly in the candidate tool using the exact active segment IDs from `TAIL_VALIDATED_FIXED_SEGMENTS`, including the full opening text. Define board prompts explicitly:

```python
CLOUD_FIXED_TEXTS = {
    "idiom_game/start": "好呀，我们玩成语接龙。小机仔先来：",
    "idiom_game/robot_no_reply_user_win": "小机仔暂时接不上啦，这局你赢。",
    "idiom_game/challenge_win": "挑战成功，这局你赢。",
    "idiom_game/mode_easy": "已切换到简单模式，连续接对轮数已重新计算。",
    "idiom_game/mode_normal": "已切换到普通模式，连续接对轮数已重新计算。",
    "idiom_game/mode_hard": "已切换到困难模式，连续接对轮数已重新计算。",
    "idiom_game/mode_full": "已切换到大师模式，连续接对轮数已重新计算。",
    "idiom_game/exit": "这局先到这里，小机仔把小本本合上啦。",
    "idiom_game/continue_prompt": "我们继续成语接龙吧，请说一个能接上的四字成语。",
    "idiom_game/retry": "我没听清，请再说一次。",
    "idiom_game/not_found": "这个我还没在成语词库里找到。你可以换一个四字成语再接。",
    "idiom_game/static_error": "成语语音暂时不可用，请稍后再试。",
}

BOARD_PROMPTS = {
    "idiom_game_presence_1.pcm": "你还在吗？",
    "idiom_game_misheard_1.pcm": "我没听清，请再说一次。",
    "idiom_game_idle_exit_1.pcm": "那我们下次再玩吧。",
}
```

Add a test comparing `CLOUD_FIXED_TEXTS` with the active phrase definitions so the two inventories cannot drift. Reject every requested segment containing `idioms/` or `pinyin/`.

The script must support both repository execution and temporary cloud execution:

```python
try:
    from src.providers.pcm_tail import analyze_pcm16_tail, ensure_safe_pcm16_tail
except ModuleNotFoundError:
    from pcm_tail import analyze_pcm16_tail, ensure_safe_pcm16_tail
```

The fallback is only for the `/tmp/<run>/code` candidate workspace before the new source has been deployed.

- [ ] **Step 4: Implement atomic processing and manifest output**

For each WAV candidate:

```text
read PCM16 from WAV
→ analyze source before padding
→ reject if source_complete=false
→ ensure_safe_pcm16_tail
→ write temporary WAV/PCM
→ validate format, tail, even size and board64KiB cap
→ os.replace temporary output into the candidate output directory
→ record SHA-256 and metadata
```

Use these exact functions so tests and CLI share one path:

- `read_wav_pcm16(path: Path) -> bytes`: require16kHz, mono, 16-bit, uncompressed WAV and return only PCM frames.
- `write_wav_pcm16_atomic(path: Path, pcm: bytes) -> None`: write a sibling temporary WAV with the required format, reopen and validate it, then use `os.replace()`.
- `generate_candidate_batch(*, output_root: Path, manifest_path: Path, synthesizer: Synthesizer, model: str, voice: str, max_attempts: int) -> dict`: generate the complete cloud and board inventories and fail the batch if any item exhausts its attempts.
- `validate_candidate_batch(*, candidate_root: Path, manifest_path: Path) -> dict`: verify every manifest path, SHA-256, format, tail report, board size, and the absence of `idioms/` or `pinyin/`.
- `install_board_candidates(*, candidate_root: Path, board_output_dir: Path, manifest_path: Path) -> None`: revalidate, then atomically install exactly the three named PCM files.
- `install_cloud_candidates(*, candidate_root: Path, static_audio_root: Path, manifest_path: Path) -> None`: revalidate, then atomically install exactly `CLOUD_FIXED_TEXTS` under `idiom_game/`.

The shared preparation function is complete and must be used by both cloud and board candidates:

```python
Synthesizer = Callable[[str, Path, dict], dict | None]


def prepare_candidate_pcm(pcm: bytes, *, max_bytes: int | None = None) -> bytes:
    prepared = ensure_safe_pcm16_tail(pcm)
    if max_bytes is not None and len(prepared) > max_bytes:
        raise FixedCandidateError("fixed_audio_board_size_exceeded")
    return prepared
```

`generate_candidate_batch()` calls the synthesizer into a per-attempt temporary WAV, checks the unpadded source with `analyze_pcm16_tail()`, retries only when the source endpoint is incomplete, then pads and atomically writes the validated candidate. It returns nonzero/raises if any inventory item fails after `max_attempts`; partial candidates never count as a valid batch.

The tool must not overwrite production `data/static_audio`; require an explicit output directory different from `settings.static_audio_path` unless `--install-validated` is provided during a later deployment step.

Expose these exact CLI operations:

```text
generate --output-root PATH --manifest-path PATH --backend realtime --max-attempts 3
validate --candidate-root PATH --manifest-path PATH
install-board --candidate-root PATH --board-output-dir PATH --manifest-path PATH
install-cloud --candidate-root PATH --static-audio-root PATH --manifest-path PATH
```

`generate` writes `cloud/idiom_game/*.wav` and `board/*.pcm` below `--output-root`. `validate` is read-only. Both install commands verify the manifest SHA-256 before any replacement and use temporary sibling files plus `os.replace()`.

- [ ] **Step 5: Run processor tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_prepare_idiom_fixed_audio.py tests/test_pcm_tail.py -q
```

Expected: all tests pass.

---

### Task 5: Generate, Return, and Install Fixed Candidates

**Files:**
- Modify generated binaries only after validation:
  - `esp_idf_demo/spiffs/idiom_game_presence_1.pcm`
  - `esp_idf_demo/spiffs/idiom_game_misheard_1.pcm`
  - `esp_idf_demo/spiffs/idiom_game_idle_exit_1.pcm`
- Create: `docs/superpowers/summaries/2026-07-16-idiom-fixed-audio-tail-current-state.md`

**Interfaces:**
- Consumes: explicit fixed texts and the server's configured DashScope realtime TTS model/voice.
- Produces: one validated candidate batch and matching local/cloud SHA-256 records.

- [ ] **Step 1: Create a cloud temporary output directory**

Create the same run ID from local PowerShell, create a remote `/tmp` directory, and upload only the generator plus its quality helper; never write into the remote Git worktree:

```powershell
$RunId = "idiom_fixed_$(Get-Date -Format yyyyMMdd_HHmmss)"
$RemoteCandidateRoot = "/tmp/$RunId"
ssh -p 2223 intern2@CLOUD_HOST "mkdir -p '$RemoteCandidateRoot/code' '$RemoteCandidateRoot/output'"
scp -P 2223 `
    .\scripts\prepare_idiom_fixed_audio.py `
    .\src\providers\pcm_tail.py `
    intern2@CLOUD_HOST:"$RemoteCandidateRoot/code/"
```

- [ ] **Step 2: Generate only the fixed inventory with the configured realtime model and voice**

Run generation against the explicit inventory from Task 4 with at most three attempts per failed endpoint. The script loads the existing remote `src.providers.realtime_tts` from the project but loads the uploaded tail helper from its own directory. Do not pass `phrase,idiom,pinyin` and do not run the all-category prebuild command:

```powershell
ssh -p 2223 intern2@CLOUD_HOST `
    "cd /home/intern2/projects/20260709_Tiny_Machine_Robot && PYTHONPATH='$RemoteCandidateRoot/code:/home/intern2/projects/20260709_Tiny_Machine_Robot' .venv/bin/python '$RemoteCandidateRoot/code/prepare_idiom_fixed_audio.py' generate --output-root '$RemoteCandidateRoot/output' --manifest-path '$RemoteCandidateRoot/manifest.json' --backend realtime --max-attempts 3"
```

- [ ] **Step 3: Validate the cloud candidates before transfer**

Require zero failed entries, no `idioms/` paths, all cloud fixed WAVs safe, all board candidates `<=65536` bytes, and a complete SHA-256 manifest. If any condition fails, leave production untouched and stop.

```powershell
ssh -p 2223 intern2@CLOUD_HOST `
    "cd /home/intern2/projects/20260709_Tiny_Machine_Robot && PYTHONPATH='$RemoteCandidateRoot/code:/home/intern2/projects/20260709_Tiny_Machine_Robot' .venv/bin/python '$RemoteCandidateRoot/code/prepare_idiom_fixed_audio.py' validate --candidate-root '$RemoteCandidateRoot/output' --manifest-path '$RemoteCandidateRoot/manifest.json'"
```

- [ ] **Step 4: Transfer the validated candidate batch to a local temporary directory**

Use `scp -P 2223` into a directory outside the Git worktree, then run the local validator against the transferred bytes and compare every SHA-256 with the cloud manifest:

```powershell
$LocalCandidateRoot = Join-Path $env:TEMP $RunId
New-Item -ItemType Directory -Force $LocalCandidateRoot | Out-Null
scp -P 2223 -r intern2@CLOUD_HOST:"$RemoteCandidateRoot/output" $LocalCandidateRoot
scp -P 2223 intern2@CLOUD_HOST:"$RemoteCandidateRoot/manifest.json" $LocalCandidateRoot
python .\scripts\prepare_idiom_fixed_audio.py validate `
    --candidate-root "$LocalCandidateRoot\output" `
    --manifest-path "$LocalCandidateRoot\manifest.json"
```

- [ ] **Step 5: Install only the three validated board PCM files locally**

Use the candidate preparation tool to atomically replace the three SPIFFS files. Do not modify `config.h`, `sdkconfig.multinet_eval`, or any idiom audio:

```powershell
python .\scripts\prepare_idiom_fixed_audio.py install-board `
    --candidate-root "$LocalCandidateRoot\output" `
    --board-output-dir ".\esp_idf_demo\spiffs" `
    --manifest-path "$LocalCandidateRoot\manifest.json"
```

- [ ] **Step 6: Record the candidate batch**

Write model, voice, text, duration, bytes, endpoint report, and SHA-256 for all fixed candidates into the current-state report. Do not include API keys or signed provider URLs.

- [ ] **Step 7: Pause for human listening approval**

Provide WAV previews or the later hardware checklist. Do not install cloud production assets or claim perceptual success solely from RMS tests.

---

### Task 6: Regression Verification and Handoff

**Files:**
- Modify: `tests/test_esp_assets.py`
- Modify: `tests/test_tiny_esp_guards.py` only if a source guard is needed
- Modify: `docs/superpowers/summaries/2026-07-16-idiom-fixed-audio-tail-current-state.md`

**Interfaces:**
- Consumes: final code and fixed candidate batch.
- Produces: verification evidence, a safe commit scope, and exact deployment/flash instructions.

- [ ] **Step 1: Add board asset guards**

Assert each of the three PCM files is nonempty, even-sized, `<=65536`, source-complete, and has at least80ms quiet tail.

- [ ] **Step 2: Run focused regression**

```powershell
python -m pytest tests/test_pcm_tail.py tests/test_prepare_idiom_fixed_audio.py tests/test_idiom_audio_catalog.py tests/test_voice_skills.py tests/test_realtime_api.py tests/test_esp_assets.py tests/test_tiny_esp_guards.py -q --deselect tests/test_tiny_esp_guards.py::test_firmware_keeps_xiaoming_wake_word_and_volcengine_asr_default
```

Expected: all selected tests pass.

- [ ] **Step 3: Run unfiltered and filtered full suites**

```powershell
python -m pytest -q
python -m pytest -q --deselect tests/test_tiny_esp_guards.py::test_firmware_keeps_xiaoming_wake_word_and_volcengine_asr_default
```

Expected: unfiltered has only the documented stale Volcengine assertion; filtered suite passes with no hidden failures.

- [ ] **Step 4: Build ESP-IDF 5.5.4**

```powershell
cd D:\20260709_Tiny_Machine_Robot-merge\esp_idf_demo
. D:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1
idf.py build
```

Expected: application and `storage.bin` build successfully; all three fixed PCM files are included.

- [ ] **Step 5: Audit scope and protected files**

Run `git diff --check`, inspect `git status --short`, confirm no `idioms/*`, `config.h`, Multinet evaluation config, provider key, signed URL, or bundle is staged.

- [ ] **Step 6: Report commit recommendation without committing**

Summarize tests, build size, candidate hashes, remaining perceptual hardware check, and whether the change is safe to submit. Wait for the user's explicit `可提交并推送` before staging or committing.
