# Tiny Coffee BLE Mini Program Design

## Goal

Build the first WeChat Mini Program companion for Tiny Coffee Machine / 小机仔. The app provisions devices through BLE only, binds devices to a user, shows the latest three chat rounds, and lets the user adjust volume, switch voice, and upload an avatar.

## Decisions

- Provisioning uses BLE only. SoftAP and Wi-Fi hotspot provisioning are not part of this mini program flow.
- The first implementation uses BluFi-compatible provisioning on ESP32-S3 instead of a custom GATT protocol.
- Product development starts with a BluFi compatibility spike on the target ESP32-S3 hardware and real WeChat clients. The spike must pass before mini program business features are built on top of BluFi.
- The mini program can read the phone's currently connected Wi-Fi SSID when permissions and platform support allow it, but it never reads the Wi-Fi password. The user enters the password.
- Chat history, avatar, voice choice, and device settings live on the Guangzhou server. The device does not talk to WeChat directly.
- Device identity is immutable. The firmware derives `device_id` from the ESP32-S3 eFuse base MAC at first boot and uses the same value for BLE provisioning, cloud binding, realtime sessions, settings sync, and future OTA.
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
- Device raw MAC stored only if needed for support diagnostics.
- User-device binding.
- Device settings: nickname, avatar URL, volume, voice, and monotonically increasing settings revision.
- Chat history rows linked to device ID and session ID.

Required API capabilities:

- Exchange `wx.login` code for a user session.
- Bind a provisioned device to the current user.
- List the user's devices.
- Read and update device settings.
- Return the latest three chat rounds for a device.
- Accept avatar uploads and return an HTTPS avatar URL.
- Let firmware pull settings by device ID using the same trusted device identity already used by the realtime device path.

All `/api/wx/v1` responses include `"api_version": "1.0"`. Firmware settings responses use additive JSON fields so older firmware can ignore fields added by future mini program releases.

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
- Compute `device_id = "tc-s3-" + lowercase_hex(HMAC_SHA256(efuse_base_mac, TINY_COFFEE_DEVICE_ID_SALT))[0:16]`.
- Persist and reuse this `device_id`; never generate a new ID from Wi-Fi connection state, boot count, random UUID, or server response.
- Use the same `device_id` in BLE identity response, backend binding, realtime headers, settings sync, and future OTA.
- Use the last four hex characters of the eFuse MAC as the development pairing PIN. Production packaging should print a per-device pairing PIN or QR payload; the MAC-last-four PIN remains only as the first batch fallback.

BLE security:

- Do not ship a no-security BluFi mode.
- Use BluFi security with encrypted credential transport.
- Require a pairing PIN check before accepting Wi-Fi credentials. The mini program asks the user for the PIN from the package label or uses a QR payload. The device verifies the PIN-derived proof against a provisioning nonce.
- Rate-limit failed PIN attempts and keep the device in a retryable provisioning state.
- Wi-Fi password must never be logged by firmware, mini program, or backend.

Provisioning state machine:

- Unprovisioned boot: start BLE provisioning and advertise `XiaoJiZi-xxxx`.
- Provisioned and Wi-Fi connected: stay in normal realtime mode.
- Provisioned and Wi-Fi connection fails: enter BLE provisioning for reconfiguration.
- GPIO7 short press: keep current voice/wake behavior.
- GPIO7 long press for 5 seconds while idle: stop realtime capture/playback, clear saved Wi-Fi credentials, clear local binding token if present, reboot into BLE provisioning.
- GPIO7 long press during an active conversation: ignore the reprovision request until the conversation finishes; do not interrupt a live audio session unexpectedly.
- BLE provisioning active: realtime Opus capture/playback is paused and any active realtime WebSocket is closed before BLE starts.
- BLE provisioning success: save Wi-Fi credentials, reconnect Wi-Fi, report device identity to the mini program, then return to normal mode.

Firmware responsibilities:

- Start BLE provisioning only when needed.
- Accept Wi-Fi credentials through BluFi.
- Attempt Wi-Fi connection and report success or failure through BLE.
- Expose device identity and firmware version to the mini program after provisioning.
- Persist Wi-Fi credentials in the existing Wi-Fi storage path.
- Pull device settings from Guangzhou server after Wi-Fi connects, before every conversation, and during idle operation.
- Apply volume locally.

Firmware must not break the realtime Opus audio path, wake-word path, or current GPIO controls.

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
6. While idle and online, firmware polls settings every 30 seconds if no active realtime WebSocket exists.
7. If a realtime WebSocket is active, the server pushes a `settings_delta` event over that connection after a mini program settings update. If the device is not connected, the next pre-conversation pull or 30-second idle poll receives the change.
8. Firmware applies volume locally when a settings update arrives. If playback is active, the new volume applies to the next playback chunk the codec accepts.
9. Server-side realtime TTS uses the selected voice for new sessions. Voice changes do not interrupt an active TTS stream; the mini program labels voice changes as effective from the next conversation.
10. The mini program shows a saved/downstream state: `已保存`, `等待设备同步`, or `已下发`.

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

The firmware must report provisioning success, Wi-Fi failure, and timeout states over BLE. If provisioning fails, the device remains discoverable long enough for the user to retry from the mini program.

Backend errors use stable machine-readable codes in addition to human text. Required codes include `DEVICE_ALREADY_BOUND`, `DEVICE_NOT_BOUND`, `DEVICE_SETTINGS_CONFLICT`, `AVATAR_UPLOAD_FAILED`, and `PROVISIONING_BIND_EXPIRED`.

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
- Changing volume in the mini program is pulled before the next conversation and can be pushed during an active realtime WebSocket.
- Changing voice in the mini program makes the next realtime TTS session use the selected voice.
- Uploading an avatar stores and displays the avatar URL in the mini program.
- `/api/wx/v1` responses include `api_version`.
- Unknown future fields in settings responses are ignored by firmware.
- Existing realtime Opus conversations continue to work.
- Wake word and GPIO controls continue to work.

Recommended verification:

- Unit tests for backend settings and history APIs.
- Backend integration tests for bind-device and latest-three-history behavior.
- Firmware guard tests for BLE provisioning compile flags and SoftAP exclusion from the mini program path.
- Firmware tests or log assertions that GPIO7 short press remains voice/wake and GPIO7 long press enters BLE provisioning only while idle.
- Backend tests for duplicate binding, already-bound errors, settings revision increments, and `api_version`.
- Manual BLE provisioning test on COM6 hardware.
- Manual mini program test on at least one Android phone and one iPhone before public use.

## Out Of Scope

- OTA control from the mini program.
- Payment, coupons, gift QR code redemption, or kiosk interaction.
- Screen rendering on the device.
- Multi-device family management beyond listing and selecting bound devices.
- Silent Wi-Fi password import from the phone.
- SoftAP provisioning flow.
