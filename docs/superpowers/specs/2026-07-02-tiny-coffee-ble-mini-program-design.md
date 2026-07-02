# Tiny Coffee BLE Mini Program Design

## Goal

Build the first WeChat Mini Program companion for Tiny Coffee Machine / 小机仔. The app provisions devices through BLE only, binds devices to a user, shows the latest three chat rounds, and lets the user adjust volume, switch voice, and upload an avatar.

## Decisions

- Provisioning uses BLE only. SoftAP and Wi-Fi hotspot provisioning are not part of this mini program flow.
- The first implementation uses BluFi-compatible provisioning on ESP32-S3 instead of a custom GATT protocol.
- Product development starts with a BluFi compatibility spike on the target ESP32-S3 hardware and real WeChat clients. The spike must pass before mini program business features are built on top of BluFi.
- The mini program can read the phone's currently connected Wi-Fi SSID when permissions and platform support allow it, but it never reads the Wi-Fi password. The user enters the password.
- Chat history, avatar, voice choice, and device settings live on the Guangzhou server. The device does not talk to WeChat directly.
- Device identity is immutable. The firmware uses the ESP32-S3 eFuse base MAC as `device_id = "tc-s3-" + lowercase_hex(efuse_base_mac)` and uses the same value for BLE provisioning, cloud binding, realtime sessions, settings sync, and future OTA.
- Settings synchronization uses one revision rule across all fetch paths: the server is authoritative, every response carries `settings_revision`, and the firmware applies settings only at safe session boundaries.
- The first implementation does not push settings over the realtime audio WebSocket. It uses a pre-conversation pull and a 30-second idle poll.
- OTA is out of scope for this mini program phase.
- The screen is a future hardware addition. Avatar upload is saved now so the future screen can display it without changing the mini program user flow.

## Project Context

The current firmware already has Wi-Fi management and a config-mode path, but the approved mini program direction does not reuse SoftAP. The current realtime Opus conversation path stays intact: ASR is Volcengine, LLM is Qwen, and realtime TTS is used for spoken responses. The Guangzhou backend at `tiny.praystack.top` is the cloud authority for user-facing device state.

Relevant current repo surfaces:

- Firmware network entry points live around `esp_idf_demo/main/app_network.cc`.
- Realtime cloud endpoints live around `src/api/realtime.py`.
- OTA code exists but remains inactive for this phase.
- Existing guard tests live in `tests/test_tiny_esp_guards.py` and should be extended for firmware configuration invariants.

## Approaches Considered

### Recommended: BluFi plus a 小机仔 business shell

Use ESP32 BluFi-compatible BLE provisioning in firmware. The mini program reuses mature BluFi ideas and libraries where licensing permits, then wraps them in custom 小机仔 pages for binding, settings, history, and avatar upload.

Tradeoffs:

- Best balance of reliability, speed, and maintainability.
- Avoids inventing BLE packet framing, retries, and status semantics.
- Requires adapting sample mini program code into this repo's product structure.
- Requires an explicit WeChat BLE compatibility spike before product work because WeChat write calls, callbacks, MTU, and platform behavior can vary.

### ESP-IDF provisioning manager over BLE

Use ESP-IDF's provisioning manager and implement the corresponding BLE client behavior in the mini program.

Tradeoffs:

- Official and structured on the firmware side.
- More mini program protocol work than BluFi samples.
- Good fallback if BluFi sample compatibility is poor.

### Custom BLE GATT JSON protocol

Define a custom service with characteristics for Wi-Fi credentials, status, and device identity.

Tradeoffs:

- Fastest to sketch.
- Highest compatibility and security risk.
- Requires custom chunking, retries, error handling, and future migrations.

The selected approach is BluFi plus a 小机仔 business shell.

## Phase 0 BluFi Compatibility Spike

Before implementing the product mini program, the team must run a focused BluFi spike on the target ESP32-S3 board and real WeChat clients.

Spike scope:

- Build and flash a minimal BluFi firmware on the target board.
- Run a WeChat mini program BluFi client adapted from an approved open-source reference.
- Provision the board to a normal 2.4 GHz Wi-Fi network through BLE.
- Verify success on at least one Android phone and one iPhone.
- Capture BLE logs for scan, connect, service discovery, write, notify, Wi-Fi success, and Wi-Fi failure.
- Implement mini program write queueing as single-flight BLE writes: split payloads into safe chunks, send one `wx.writeBLECharacteristicValue` at a time, wait for the callback, then send the next chunk.
- Use write timeouts, retry with backoff, and fail with a visible user error after bounded retries.
- Confirm the firmware correctly reassembles chunks and reports provisioning timeout or wrong-password failure.

Exit criteria:

- Three consecutive successful provisioning runs on Android.
- Three consecutive successful provisioning runs on iPhone.
- One wrong-password run returns a clear failure to the mini program.
- One interrupted BLE connection run returns the user to a retryable state.
- No product pages or backend binding work starts until this spike passes.

## Mini Program UX

### Device Add Page

The add-device flow scans for BLE advertisements named like `XiaoJiZi-xxxx`. The user selects a device, the mini program connects, reads the phone's current Wi-Fi SSID when available, asks the user for the password, and sends credentials through BluFi. The page shows each state explicitly: Bluetooth permission, scanning, connecting, provisioning, device joining Wi-Fi, cloud binding, and success.

### Device Home Page

The home page shows the bound 小机仔 device, online status, nickname, avatar, current volume, and current voice. It is the first screen after binding.

### Chat History Page

The history page shows only the most recent three question-and-answer rounds for the selected device. History comes from Guangzhou server records generated by the existing realtime pipeline.

### Settings Page

The settings page lets the user adjust volume, switch voice, and edit the device nickname. Volume is a numeric setting applied by firmware. Voice selection is a server-side realtime TTS setting used when a new conversation starts.

### Avatar Page

The avatar page uses WeChat media selection and HTTPS upload to the Guangzhou server. The server stores the avatar URL against the device. The mini program displays the uploaded avatar immediately. Firmware use of the avatar is deferred until screen hardware exists.

## Backend Design

The Guangzhou backend gains mini program APIs under the `/api/wx/v1` prefix. These routes run in the same FastAPI service as the realtime APIs, but remain route-isolated from `/api/v3/realtime`, `/api/v5/realtime`, and `/api/v5/ota`.

Required data concepts:

- WeChat user identity keyed by `openid`.
- Device identity keyed by immutable `device_id`.
- Device raw MAC stored as lowercase hex without separators for support diagnostics.
- User-device binding.
- Device settings: nickname, avatar URL, volume, voice, and monotonically increasing settings revision.
- Chat history rows linked to device ID and session ID.

Required API capabilities:

- Exchange `wx.login` code for a user session at `/api/wx/v1/login`.
- Bind a provisioned device to the current user.
- List the user's devices.
- Read and update device settings.
- Return the latest three chat rounds for a device.
- Accept avatar uploads and return an HTTPS avatar URL.
- Let firmware pull settings by device ID using the same trusted device identity already used by the realtime device path.

All `/api/wx/v1` responses include `"api_version": "1.0"`. Firmware settings responses use additive JSON fields so older firmware can ignore fields added by future mini program releases.

Mini program authentication:

- The mini program calls `wx.login` and sends the returned code to `/api/wx/v1/login`.
- The backend exchanges the code with WeChat's code-to-session API using the configured appid and app secret.
- The backend stores or updates the user row keyed by `openid`.
- The backend returns a signed JWT with `sub = openid`, `iat`, and `exp`. The token lifetime is 7 days.
- The mini program stores the JWT and sends `Authorization: Bearer <token>` on all `/api/wx/v1` requests after login.
- The backend validates the JWT locally. It does not call WeChat on every mini program request.
- The WeChat `session_key` is never returned to the mini program and is not used as an API bearer token.
- On 401 or near expiry, the mini program calls `wx.login` again and replaces the JWT.

Binding rules:

- First bind creates the binding for `openid` and `device_id`.
- Binding the same device again by the same `openid` is idempotent and returns the existing binding.
- Binding a device owned by another `openid` fails with `DEVICE_ALREADY_BOUND`.
- The mini program displays: `该设备已被其他用户绑定，请联系管理员重置`.
- Owner unbind is supported from the mini program.
- Ownership transfer is not a silent rebind. Transfer requires the current owner to unbind, an admin reset, or a physical factory reset flow that clears the cloud binding token.

The backend should keep the existing realtime Opus APIs stable. Mini program APIs are additive.

## Firmware Design

Firmware adds a BLE provisioning mode that can be entered when the device has no valid Wi-Fi credentials, when Wi-Fi is unavailable after saved credentials fail, or when the user long-presses GPIO7 for 5 seconds. Short GPIO7 behavior for normal interaction remains unchanged. GPIO0 boot-key reconfiguration can remain as a developer fallback, but the product pairing gesture is GPIO7 long press. The BLE advertising name uses `XiaoJiZi-` plus a short device suffix.

Device identity:

- Read the ESP32-S3 eFuse base MAC.
- Compute `device_id = "tc-s3-" + lowercase_hex(efuse_base_mac)`. The MAC hex is 12 lowercase characters without separators.
- Persist and reuse this `device_id`; never generate a new ID from Wi-Fi connection state, boot count, random UUID, or server response.
- Use the same `device_id` in BLE identity response, backend binding, realtime headers, settings sync, and future OTA.
- Store the raw MAC and `device_id` mapping on the backend for support diagnostics. The mini program does not display raw MAC by default.

BLE security:

- Do not ship a no-security BluFi mode.
- Use BluFi security with encrypted credential transport.
- Require a pairing PIN check before accepting Wi-Fi credentials. First-stage production must print a per-device 4-digit numeric PIN on the device body or packaging. This is a launch gate.
- Store the production PIN in the default NVS partition under key `pairing_pin` as `u16` during manufacturing.
- Factory tooling writes `pairing_pin` with `nvs_partition_gen.py` before flashing the NVS partition, or with a project-owned `esptool.py` manufacturing script that writes the generated NVS image. The implementation plan must pick one path and make it a repeatable command.
- If `pairing_pin` is missing from NVS, firmware falls back to PIN `0000`, logs `pairing_pin_missing_using_0000`, and continues only so lab bring-up remains possible. Production test treats that log line as FAIL.
- The mini program asks the user for the printed PIN or scans a package QR payload.
- Use a nonce-based challenge response before sending Wi-Fi credentials: the device sends a provisioning nonce, the mini program sends a PIN-derived proof for `device_id + nonce`, and the device accepts credentials only after proof verification.
- Development builds may temporarily disable PIN verification only for lab BluFi spike work. This mode must be visibly labeled as lab-only and must fail production guard checks.
- Rate-limit failed PIN attempts and Wi-Fi credential failures using the provisioning retry rules below.
- Wi-Fi password must never be logged by firmware, mini program, or backend.

Provisioning state machine:

- Unprovisioned boot: start BLE provisioning and advertise `XiaoJiZi-xxxx`.
- Provisioned and Wi-Fi connected: stay in normal realtime mode.
- Provisioned and Wi-Fi connection fails: enter BLE provisioning for reconfiguration.
- GPIO7 short press: keep current voice/wake behavior.
- GPIO7 long press for 5 seconds while idle: stop realtime capture/playback, clear saved Wi-Fi credentials, clear local binding token if present, reboot into BLE provisioning.
- GPIO7 long press during an active conversation: ignore the reprovision request until the conversation finishes; do not interrupt a live audio session unexpectedly.
- BLE provisioning active: realtime Opus capture/playback is paused and any active realtime WebSocket is closed before BLE starts.
- BLE provisioning success: save Wi-Fi credentials, reconnect Wi-Fi, send a `PROVISIONING_SUCCESS` BLE notify that includes device identity and firmware version, stop BLE advertising, keep the current BLE connection open, and wait for the mini program to close the BLE connection.

Successful provisioning close handshake:

- Firmware does not actively disconnect the BLE connection on the success path.
- The mini program treats `PROVISIONING_SUCCESS` as a terminal success state, immediately updates the UI to success or binding progress, sets a local `expectedDisconnect` flag, and calls `wx.closeBLEConnection()`.
- When `onBLEConnectionStateChange` reports `connected: false` while `expectedDisconnect` is set or a terminal success state has been reached, the mini program suppresses the generic "Bluetooth disconnected" error UI.
- If the BLE connection drops before `PROVISIONING_SUCCESS`, the mini program shows a retryable connection-lost error.
- Firmware may actively disconnect BLE on failure, timeout, cooldown, or max-failure paths. Those disconnects are not marked as expected by the mini program unless an explicit terminal success was received.

Provisioning retry rules:

- Each BLE provisioning window lasts 10 minutes from advertising start.
- If provisioning does not succeed within 10 minutes, firmware disconnects any BLE client, stops BLE advertising, and enters provisioning timeout idle state.
- In provisioning timeout idle state, pressing GPIO7 restarts a new 10-minute BLE provisioning window. Power cycling the device also starts a new window when no valid Wi-Fi credentials exist.
- On successful provisioning, firmware immediately stops BLE advertising but does not actively disconnect the provisioning BLE session. The mini program closes the BLE connection after receiving `PROVISIONING_SUCCESS`.
- Wrong Wi-Fi password, Wi-Fi join failure, and PIN verification failure increment the same in-memory failure counter for the current provisioning window.
- The first five failures in a provisioning window are retryable without cooldown.
- Starting with the sixth failure, firmware enforces exponential cooldown before accepting another PIN proof or Wi-Fi credential attempt: 30 seconds, 60 seconds, 120 seconds, then 240 seconds, capped at 300 seconds for later failures.
- After 10 consecutive failures in one provisioning window, firmware ends the window early, stops BLE advertising, and requires GPIO7 or power cycle to start a new provisioning window.
- The mini program displays the cooldown countdown when firmware reports `PROVISIONING_COOLDOWN`.
- The failure counter resets after successful provisioning or when a new provisioning window starts.

Firmware responsibilities:

- Start BLE provisioning only when needed.
- Accept Wi-Fi credentials through BluFi.
- Attempt Wi-Fi connection and report success or failure through BLE.
- Expose device identity and firmware version to the mini program after provisioning.
- Persist Wi-Fi credentials in the existing Wi-Fi storage path.
- Pull device settings from Guangzhou server after Wi-Fi connects, before every conversation, and during idle operation.
- Apply volume locally.

Firmware must not break the realtime Opus audio path, wake-word path, or current GPIO controls.

## Settings Synchronization

The server is the source of truth for settings when it returns a monotonic settings snapshot. Each settings row starts at `settings_revision = 1` when the device is first bound or its default settings are created. Every accepted mini program settings write increments the revision by 1. A server response with a lower revision than the firmware cache is treated as a stale cache or routing fault, not as an instruction to roll back.

Firmware state:

- On factory boot, local `current_revision = 0`.
- The firmware persists `current_revision` and the last applied settings snapshot to NVS after every successful apply.
- Reboot loads the persisted revision and snapshot before network sync.
- Each conversation uses a frozen `session_settings` snapshot captured immediately before ASR starts.

Fetch and apply rules:

- Firmware fetches settings after Wi-Fi connects.
- Firmware fetches settings before every conversation, before ASR capture starts.
- Firmware polls settings every 30 seconds only while idle and online.
- There is no first-version settings push over `/api/v5/realtime/opus-stream`.
- If a response has `settings_revision > current_revision` and no conversation is active, firmware applies it immediately, persists it, and updates `current_revision`.
- If a response has `settings_revision > current_revision` while a conversation is active, firmware stores it as `pending_settings` and applies it after the conversation finishes.
- If a response has `settings_revision == current_revision`, firmware ignores it.
- If a response has `settings_revision < current_revision`, firmware treats it as stale or inconsistent data, logs a warning, ignores the snapshot, keeps the current settings, and schedules an extra settings pull with backoff.
- If three consecutive settings pulls return `settings_revision < current_revision`, firmware enters `revision_stale_degraded` mode, keeps the current settings, reports `settings_revision_stale` telemetry on the next successful cloud request, and stretches idle settings polling from 30 seconds to 5 minutes.
- In `revision_stale_degraded` mode, pre-conversation settings pulls still run before every conversation. If they continue to return a lower revision, firmware ignores them and keeps the current settings.
- `revision_stale_degraded` mode is cleared when firmware receives `settings_revision >= current_revision` or after device reboot.
- Volume, voice, nickname, and avatar changes never mutate `session_settings` after ASR has started. Volume changes and voice changes both take effect no earlier than the next conversation once a session is active.

Settings API behavior:

- Mini program setting writes are last-write-wins. The client does not send an expected revision and the backend does not perform optimistic-lock conflict rejection in the first implementation.
- A successful write returns the full settings snapshot with the new `settings_revision`.
- Firmware pull responses include `api_version`, `device_id`, `settings_revision`, `nickname`, `avatar_url`, `volume`, `voice`, and `updated_at`.
- Unknown fields in a firmware settings response are ignored.

## Data Flow

Provisioning:

1. User opens mini program add-device page.
2. Mini program requests Bluetooth and Wi-Fi information permissions.
3. Mini program scans for `XiaoJiZi-xxxx`.
4. User selects a device.
5. Mini program connects over BLE.
6. Mini program fills the current SSID when available.
7. User enters Wi-Fi password.
8. Mini program sends credentials through BluFi.
9. Firmware connects to Wi-Fi.
10. Firmware reports result and identity over BLE.
11. Mini program calls Guangzhou backend to bind the device.
12. Backend records the binding and returns current settings.

Conversation history:

1. Device talks to the existing realtime cloud pipeline.
2. Backend records successful question-and-answer rounds by device ID.
3. Mini program requests the latest three rounds for the selected device.

Settings:

1. User changes volume, voice, nickname, or avatar in the mini program.
2. Backend persists the setting.
3. Backend increments the device settings revision.
4. Firmware pulls settings after Wi-Fi connection.
5. Firmware pulls settings before every conversation, before ASR capture starts.
6. While idle and online, firmware polls settings every 30 seconds.
7. Firmware applies a newer revision immediately only while idle. During a conversation, newer settings are queued as pending and applied after the session ends.
8. Server-side realtime TTS uses the selected voice from the frozen `session_settings` snapshot for each new session.
9. The mini program shows a saved/downstream state: `已保存`, `等待设备同步`, or `已下发`.

## Error Handling

The mini program must present explicit states for:

- Bluetooth permission denied.
- Bluetooth disabled.
- Device not found.
- BLE connection failed.
- BLE connection interrupted.
- Wi-Fi SSID unavailable from the phone.
- Wi-Fi password rejected or network join failed.
- Device joined Wi-Fi but cloud binding failed.
- Guangzhou server unavailable.
- Avatar upload failed.
- Device settings save failed.
- Device already bound by another user.
- Provisioning cooldown active after repeated PIN or Wi-Fi failures.
- Provisioning window expired and requires pressing GPIO7 to retry.

The firmware must report provisioning success, Wi-Fi failure, cooldown, and timeout states over BLE. Failed provisioning remains retryable within the active 10-minute window unless cooldown or max-failure rules apply.

Backend errors use stable machine-readable codes in addition to human text. Required codes include `DEVICE_ALREADY_BOUND`, `DEVICE_NOT_BOUND`, and `AVATAR_UPLOAD_FAILED`.

## Open Source Reuse

Approved reuse targets:

- TDesign Miniprogram for UI components such as forms, sliders, dialogs, upload controls, and navigation.
- Espressif and community BluFi WeChat mini program implementations as protocol references.
- WeChat Mini Program official APIs for Bluetooth, Wi-Fi information, login, media selection, and file upload.

The product-specific device binding, settings, history, avatar, and 小机仔 copy should be implemented in this repo rather than copied from demo apps.

Reference links:

- ESP-IDF Wi-Fi provisioning over BLE: https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32/api-reference/provisioning/wifi_provisioning.html
- WeChat/Tencent Bluetooth API notes: https://www.tencentcloud.com/zh/document/product/1219/57729
- WeChat/Tencent Wi-Fi API notes: https://intl.cloud.tencent.com/document/product/1219/57721
- WeChat/Tencent upload API: https://www.tencentcloud.com/document/product/1219/57751
- TDesign Miniprogram: https://github.com/tencent/tdesign-miniprogram
- Espressif ESP-Config-WeChat: https://github.com/EspressifApps/ESP-Config-WeChat
- SmartArduino DOIT_AI_BluFi: https://github.com/SmartArduino/DOIT_AI_BluFi
- Ai-Thinker WeChat Mini ESP32-C3 example: https://github.com/Ai-Thinker-Open/Ai-Thinker-Open-WechatMini-ESP32-C3

## Testing And Acceptance

Acceptance criteria:

- The Phase 0 BluFi spike passes on target hardware before product mini program pages are implemented.
- A new device can be provisioned through BLE without SoftAP.
- After provisioning, the mini program binds the device to the user.
- The same immutable `device_id` appears in BLE provisioning, backend binding, realtime session logs, and settings sync.
- Binding the same device twice by the same user is idempotent.
- Binding a device owned by another user returns `DEVICE_ALREADY_BOUND` and shows a clear mini program message.
- The user can see the device in the mini program device list.
- The latest three real chat rounds are visible for the selected device.
- Changing volume in the mini program is pulled before the next conversation or by the 30-second idle poll. If a conversation is active, the change is queued and applies after the conversation ends.
- Changing voice in the mini program makes the next realtime TTS session use the selected voice.
- Uploading an avatar stores and displays the avatar URL in the mini program.
- `/api/wx/v1` responses include `api_version`.
- Unknown future fields in settings responses are ignored by firmware.
- Firmware persists `current_revision` to NVS and handles `>`, `==`, and `<` revision responses exactly as specified.
- After three consecutive stale lower-revision responses, firmware enters degraded mode and changes idle polling to 5 minutes while preserving pre-conversation pulls.
- `/api/wx/v1/login` returns a 7-day JWT and subsequent mini program API calls use `Authorization: Bearer`.
- Production builds require printed/stored pairing PIN verification; lab-only no-PIN mode cannot pass production guard checks.
- Missing `pairing_pin` falls back to `0000` only with `pairing_pin_missing_using_0000` warning, and production test fails on that warning.
- BLE provisioning stops advertising after success or after a 10-minute timeout.
- Successful provisioning does not display a transient "Bluetooth disconnected" error in the mini program; the success notification is processed before the client closes BLE.
- PIN and Wi-Fi failures share the specified cooldown and max-failure behavior.
- Existing realtime Opus conversations continue to work.
- Wake word and GPIO controls continue to work.

Recommended verification:

- Unit tests for backend settings and history APIs.
- Backend integration tests for bind-device and latest-three-history behavior.
- Firmware guard tests for BLE provisioning compile flags and SoftAP exclusion from the mini program path.
- Firmware tests or log assertions that GPIO7 short press remains voice/wake and GPIO7 long press enters BLE provisioning only while idle.
- Backend tests for login token issuance, duplicate binding, already-bound errors, settings revision increments, last-write-wins settings writes, and `api_version`.
- Firmware tests or log assertions for settings revision ordering, pending apply during active conversations, stale lower-revision rejection, degraded 5-minute polling after three stale responses, degraded-mode reset on reboot or valid revision, stale-revision telemetry after three repeats, and NVS revision persistence.
- Factory/provisioning tests for NVS `pairing_pin` write, missing-PIN fallback warning, and production-test failure on `pairing_pin_missing_using_0000`.
- Firmware tests or log assertions for provisioning 10-minute timeout, BLE advertising stop on success, cooldown after repeated failures, and max-failure session stop.
- Mini program tests or manual QA for the success close handshake: `PROVISIONING_SUCCESS` updates UI first, `wx.closeBLEConnection()` is called by the client, and the expected disconnect callback is not shown as an error.
- Manual BLE provisioning test on COM6 hardware.
- Manual mini program test on at least one Android phone and one iPhone before public use.

## Out Of Scope

- OTA control from the mini program.
- Payment, coupons, gift QR code redemption, or kiosk interaction.
- Screen rendering on the device.
- Multi-device family management beyond listing and selecting bound devices.
- Silent Wi-Fi password import from the phone.
- SoftAP provisioning flow.
- Settings push over the realtime audio WebSocket.
- Optimistic-lock settings conflict handling.
