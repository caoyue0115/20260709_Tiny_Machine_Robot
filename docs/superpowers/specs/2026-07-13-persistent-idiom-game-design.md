# Persistent Idiom Game Design

## Goal

Add a persistent idiom-game voice session to the existing ESP32-S3 ASR-LLM-TTS system while preserving the ordinary coffee question flow. During a game, the board keeps one WebSocket connection open, but creates cloud ASR work only while the user is actually speaking. Idiom-game playback uses pre-generated static audio only.

## Repository Constraints

- Work only in `D:\20260709_Tiny_Machine_Robot-merge` on the current feature branch.
- Do not modify the 0701 repository, KWS experiment files, `esp_idf_demo/main/config.h`, or `esp_idf_demo/sdkconfig.multinet_eval`.
- Do not commit or push until the user explicitly authorizes a commit.
- After implementation, report whether the change is ready to commit and why.

## Chosen Architecture

Use a dedicated persistent idiom-game WebSocket endpoint. Refactor reusable Opus decoding, ASR, and realtime-session work out of the existing single-turn endpoint where needed, but leave the normal coffee endpoint's external behavior unchanged. Do not add a persistent mode flag to the normal endpoint and do not duplicate the complete existing endpoint.

Game state remains in the existing in-memory store keyed by `device_id`. It must survive WebSocket disconnect and reconnect while the same cloud process remains alive. Persistence across process restart or multiple workers is out of scope.

## Idiom Reply Behavior

The initial spoken reply remains:

```text
好呀，我们玩成语接龙。小机仔先来：{成语}。
```

Its audio plan is exactly:

```text
idiom_game/start
idiom_game/robot_first
idioms/{成语}
```

After a valid user turn, the robot answer text is only the next four-character idiom and its audio plan is exactly:

```text
idioms/{成语}
```

A deterministic or LLM-classified repeat request returns only `last_robot_word`, does not advance the game, and uses only `idioms/{last_robot_word}`. The state initializes and updates `last_robot_word` whenever the robot selects its opening word or a successful reply.

Invalid idioms, already-used idioms, difficulty changes, wins, mode changes, and exits retain complete fixed explanations. Existing `turn_prompt` and `pinyin/*` assets remain in the repository but are not referenced by normal start, reply, or repeat plans.

## Intent Ordering and LLM Contract

Every active-game utterance is handled in this order:

```text
deterministic control intent
-> local idiom dictionary
-> one structured LLM fallback
-> static audio response
```

Deterministic controls include broad exit expressions, repeat expressions, and difficulty changes. An exit clears state before any idiom lookup. Repeat returns `last_robot_word` without changing state. Empty input, pure noise, and obviously meaningless short phrases do not invoke the LLM.

The one fallback request returns:

```json
{
  "intent": "idiom | exit | repeat | easy | hard | invalid | off_topic",
  "normalized_idiom": "",
  "first_py": "",
  "last_py": "",
  "is_idiom": false,
  "matches_expected_pinyin": false,
  "confidence": 0.0
}
```

For `intent == idiom`, the server accepts the result only when all of these are true:

- `is_idiom` is true.
- `normalized_idiom` contains exactly four Chinese Han characters.
- `confidence` meets the existing configured threshold.
- `normalize_pinyin(first_py)` equals the state's `expected_py`.
- `normalize_pinyin(last_py)` is non-empty and valid.

The server computes this validation itself. `matches_expected_pinyin` is diagnostic-only. `normalize_pinyin()` remains the single normalization implementation and removes tones, lowercases, and normalizes `ü` to `v`. Missing or malformed required idiom fields produce `invalid` behavior without changing game state. Control intents ignore the idiom and pinyin fields.

## Static Audio Policy

Idiom mode never invokes runtime dynamic TTS. Each idiom result maps to a static plan:

- Start: `start + robot_first + idiom`.
- Normal reply: `idiom`.
- Repeat: `last_robot_word`'s idiom audio.
- Difficulty: `mode_easy` or `mode_hard`.
- Exit: `exit`.
- Invalid idiom: `not_found` or the existing complete repeated/wrong-prefix plan as applicable.
- Off-topic input: `continue_prompt`.
- LLM failure, timeout, or low confidence: a fixed retry prompt.

At service startup, validate every required fixed idiom-game asset by opening and inspecting it, not merely by checking file existence. Audio must decode as 16 kHz, mono, signed 16-bit PCM. A missing or invalid fixed asset maps at runtime to `idiom_game/static_error`. If `idiom_game/static_error` itself is missing or invalid, startup fails.

Validate idiom audio with the same format rules. Exclude any idiom whose asset is missing or invalid from both the opening pool and every robot reply pool. The robot must never select an unplayable idiom. If no playable reply exists, use the existing `robot_no_reply_user_win` result. Unused `pinyin/*` assets are not part of startup validation.

## Persistent WebSocket Protocol

Add a dedicated idiom-game WebSocket endpoint. Connection establishment binds `device_id` but creates no ASR instance. The connection stays idle with heartbeat traffic only until a turn begins.

Each turn uses a board-generated `turn_id`:

```text
board: utterance_start(turn_id)
board: framed Opus binary
board: utterance_end(turn_id)
cloud: asr_final(turn_id)
cloud: done(turn_id)
```

`utterance_start` creates the per-turn Opus decoder and ASR instance. Binary audio is accepted only for the active turn. `utterance_end` stops accepting audio and signals end-of-input to ASR. The server then waits for `asr_final` or a bounded timeout, destroys the per-turn ASR and decoder resources, processes the realtime session, and sends `done`. Waiting for the final result does not upload or bill additional audio.

The original single-turn endpoint also waits for the fast skill-routing phase when its ASR text explicitly requests idiom solitaire. If that route activates the idiom skill, its otherwise backward-compatible `done` adds `skill_name`, `skill_active`, and `end_skill_state`, allowing the board to enter the persistent game even when MultiNet missed the start command. Ordinary coffee `done` payloads keep their existing field set.

`asr_final`, `error`, and `done` echo `turn_id`. The board ignores responses whose `turn_id` does not match its current turn. `done` contains at least:

```json
{
  "type": "done",
  "turn_id": "board-generated-id",
  "skill_name": "idiom_game",
  "skill_active": true,
  "end_skill_state": false,
  "audio_stream_url": "..."
}
```

The server sends `done` without closing the connection. `skill_active` reflects the post-turn state for `device_id`. Exit returns `skill_active=false` and `end_skill_state=true`.

## Error Isolation

A decoding, active-turn protocol, or ASR error destroys only that active turn's ASR/decoder resources, returns a recoverable error carrying its `turn_id`, and restores the connection to idle. It does not clear the device's game state or close the WebSocket.

When already idle, a late `utterance_end`, binary frame, or message with an invalid `turn_id` only receives an error and is discarded. It must not alter any future turn. A real network disconnect, heartbeat timeout, or service shutdown ends the connection but leaves in-memory game state intact for reconnect.

Recording duration and decoded byte limits remain enforced per turn. A board-side maximum-recording trigger sends the normal `utterance_end` sequence so ASR can finalize.

## ESP32-S3 State Machine

The board keeps only the game WebSocket continuously active. It does not continuously record to the cloud and does not keep cloud ASR active.

The explicit states are:

```text
idle WebSocket
-> reply playback
-> 200 ms echo guard
-> local VAD armed
-> active upload
-> wait for reply
```

During playback and echo guard, VAD cannot trigger an upload. Once armed, the microphone supplies small local samples to the energy VAD and a ring buffer holding at least 200 ms of real PCM. No audio is uploaded and the cloud has no ASR instance in this state.

When energy crosses the start threshold, the board sends `utterance_start`, uploads the real pre-roll first, and then streams live Opus. After 200 ms of continuous low energy, it sends `utterance_end` and immediately stops uploading. It waits for the matching `done`, plays the response, and repeats. If `end_skill_state=true`, it closes the game WebSocket, clears local game context, and restores WakeNet.

Inside an active game, the board first feeds a bounded local PCM buffer to MultiNet while the game WebSocket remains idle. A recognized difficulty or repeat command uses the existing canonical text-session path, so no cloud ASR instance is created. When MultiNet reports timeout, is unavailable, or the utterance ends without a hit, the board sends `utterance_start`, flushes the buffered real PCM as Opus, and continues/finishes the ASR turn without losing the utterance prefix.

The state machine retains maximum recording duration, game TTL, WebSocket ping/pong, bounded reconnect attempts, and reconnect using the same `device_id`. Ordinary coffee questions continue through the existing wake-and-single-turn path.

## MultiNet Scope

Register these commands:

```text
100-102: start idiom game
110-111: easy mode
120-121: hard mode
140: 我没听清
141: 我没听到
142: 再说一遍
143: 重复一遍
144: 刚才是什么
```

Remove command IDs `130` and `131`. Start commands may intercept after the normal wake word. Difficulty and repeat commands intercept only while local idiom-game context is active. A MultiNet hit submits canonical text without ASR; a miss immediately continues the same captured audio through ASR. Exits, free-form idioms, and other expressions always remain eligible for ASR. WakeNet remains responsible only for `小明同学`.

## Verification

Tests are written and observed failing before production changes. The minimum coverage is:

- Start audio contains only the two fixed prefixes and one idiom; a normal reply and repeat contain only one idiom.
- Deterministic exits and LLM `exit` clear state and never return a dictionary error.
- Deterministic and LLM `repeat` return `last_robot_word` without advancing state.
- LLM idiom validation independently checks four Han characters, threshold, normalized first pinyin, and valid last pinyin.
- Mode controls and all LLM outcomes select static plans and never dynamic TTS.
- Startup validation rejects malformed fixed audio, excludes malformed idiom audio, and fails if `static_error` is unusable.
- One WebSocket completes at least two turns and remains connected after the first `done`.
- Stale `turn_id` responses are ignored by the board and per-turn errors leave both the connection and game state usable.
- Idle stray control or binary messages do not affect the next turn.
- ESP static guards verify removal of `130/131`, addition of `140-144`, at least 200 ms real pre-roll, 200 ms trailing silence, echo guard, and persistent game-state transitions.
- Existing realtime, voice-skills, Opus, and ESP tests pass.
- ESP-IDF build succeeds without committing local configuration.

## Deployment Acceptance

After local verification, deploy the cloud code to `intern2@210.22.71.130` over SSH port `2223`, restart the service behind local port `18111`, rebuild and flash the ESP32-S3, and monitor the board. Verify entry, wake-free multi-turn play, exact four-character normal replies, repeat, broad exit handling, WakeNet restoration, and unchanged ordinary coffee behavior.

Deployment does not imply authorization to commit or push. GitHub is updated only after the user explicitly authorizes the commit workflow.
