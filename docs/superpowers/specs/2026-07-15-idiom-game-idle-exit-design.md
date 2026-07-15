# Idiom Game Idle Exit Design

## Goal

Keep the idiom-game WebSocket and board-local VAD alive between turns, create cloud ASR only after confirmed VAD, prompt once with “你还在吗？” after an empty active turn, and leave the game if no new VAD arrives for 30 seconds after that prompt.

## State Model

```text
PLAYBACK
→ 200 ms echo guard
→ VAD_IDLE (local microphone energy only; no upload and no ASR)
→ confirmed VAD
→ ACTIVE_TURN (utterance_start + pre-roll + live Opus + per-turn ASR)
→ utterance_end after trailing silence
```

An active turn with usable ASR text follows the existing idiom route and resets all presence-prompt deadlines after reply playback. An active turn that ends with an empty/noise ASR result closes only that turn, waits until at least 1.5 seconds have elapsed since VAD confirmation, and plays the board-local static prompt “你还在吗？”. The WebSocket remains connected. VAD triggering is gated during playback, then rearmed after the existing 200 ms echo guard.

After the presence prompt, 30 seconds with no confirmed VAD causes a board-local static exit prompt “那我们下次再玩吧”, an `idle_exit` WebSocket control message, current-device game-state cleanup, WebSocket closure, and WakeNet restoration. If no VAD ever occurs after a normal robot reply, a 60-second idle deadline performs the same exit. A 180-second deadline since the last usable server turn prevents repeated noise/empty turns from keeping the game alive forever.

## Protocol

The idle client sends:

```json
{
  "type": "idle_exit",
  "event_id": "<device-scoped unique id>",
  "reason": "no_vad_after_presence_prompt"
}
```

The server derives the device from the authenticated/required `X-Device-ID` connection header, clears only that device's idiom state, and replies idempotently:

```json
{
  "type": "idle_exit_ack",
  "event_id": "<same id>",
  "device_id": "<connection device>",
  "skill_name": "idiom_game",
  "skill_active": false,
  "end_skill_state": true,
  "cleared": true
}
```

An already-cleared state returns the same acknowledgement with `cleared: false`. Failure to receive the acknowledgement within two seconds does not trap the board in the game: it exits locally and the server store TTL remains the final cleanup guard.

## Empty-Turn Policy

Only empty/noise result codes such as `asr_empty_text`, `asr_no_final_text`, and `empty_decoded_audio` may trigger the presence prompt. Decoder, provider, network, and protocol errors retain the existing silent-rearm behavior. The presence prompt is played at most once between usable server turns. Later empty turns rearm VAD without repeating the prompt, while the 180-second hard deadline remains active.

## Audio and Cost Boundaries

- VAD idle samples remain on the board and maintain the existing 200 ms pre-roll ring.
- The cloud creates ASR only after `utterance_start` and destroys it after finalization or timeout.
- Neither presence nor exit prompts use runtime TTS. Both are tracked PCM16LE, 16 kHz, mono board assets.
- Prompt playback never opens an ASR turn and never uploads microphone audio.

## Isolation and Failure Rules

- All cleanup is scoped to the connection's `device_id`; a payload cannot nominate another device.
- `event_id` makes retries idempotent.
- Idle controls received during an active turn are rejected as recoverable turn errors rather than clearing unrelated state.
- A per-turn failure never closes the WebSocket or clears game state unless the board independently reaches an idle-exit deadline.
- `esp_idf_demo/main/config.h` remains local-only and is never staged or committed.

## Acceptance Criteria

- An empty ASR turn plays “你还在吗？” once, then returns to VAD with the same WebSocket.
- A confirmed VAD within 30 seconds cancels the post-prompt exit deadline and starts a normal turn.
- No VAD for 30 seconds after the prompt plays the exit prompt, sends `idle_exit`, clears only the current device, closes the game WebSocket, and restores WakeNet.
- No VAD for 60 seconds after a normal reply exits without creating ASR.
- Noise/empty turns cannot keep the game active beyond 180 seconds without a usable server turn.
- Existing explicit exit, repeat, MultiNet, persistent two-turn, and ordinary realtime behavior remain unchanged.
