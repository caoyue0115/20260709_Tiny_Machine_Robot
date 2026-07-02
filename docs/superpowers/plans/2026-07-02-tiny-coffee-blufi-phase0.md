# Tiny Coffee BluFi Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that WeChat Mini Program BluFi provisioning works reliably on the target ESP32-S3 board before building the product mini program, backend binding, or device settings features.

**Architecture:** Create an isolated Phase 0 spike under `spikes/blufi_phase0` so the production realtime Opus firmware remains untouched. The firmware starts from the ESP-IDF v5.5.4 BluFi example, adds Tiny Coffee identity, pairing PIN loading, and success notification semantics. The mini program starts from Espressif's ISC-licensed `ESP-Config-WeChat` reference, then adds single-flight BLE write queueing and the success close handshake required by the spec.

**Tech Stack:** ESP-IDF v5.5.4, ESP32-S3, BluFi with Bluedroid, default NVS partition, WeChat Mini Program JavaScript, PowerShell, pytest static guards, COM6 hardware flashing.

---

## Scope Split

The approved design covers firmware provisioning, WeChat app UX, backend APIs, settings sync, avatars, and chat history. This plan implements only Phase 0 BluFi compatibility. A subsequent plan may start product firmware/backend/mini-program work only after this plan's exit criteria pass.

## File Structure

- Create `spikes/blufi_phase0/firmware/`: standalone ESP-IDF BluFi spike copied from `C:\esp\v5.5.4\esp-idf\examples\bluetooth\blufi`.
- Create `spikes/blufi_phase0/firmware/main/tiny_blufi_phase0.h`: Tiny Coffee Phase 0 helper API.
- Create `spikes/blufi_phase0/firmware/main/tiny_blufi_phase0.c`: device ID, BLE name, pairing PIN, success notify helpers.
- Modify `spikes/blufi_phase0/firmware/main/CMakeLists.txt`: compile `tiny_blufi_phase0.c`.
- Modify `spikes/blufi_phase0/firmware/main/blufi_init.c`: advertise `XiaoJiZi-xxxx` instead of `BLUFI_DEVICE`.
- Modify `spikes/blufi_phase0/firmware/main/blufi_example_main.c`: initialize helper, send `PROVISIONING_SUCCESS`, and stop advertising without active success disconnect.
- Modify `spikes/blufi_phase0/firmware/sdkconfig.defaults`: enable BluFi and SMP for the spike.
- Create `spikes/blufi_phase0/factory_nvs/pairing_pin.csv`: repeatable factory NVS input for `pairing_pin`.
- Create `spikes/blufi_phase0/wechat_miniprogram/`: copied Espressif WeChat BluFi reference with Tiny Coffee spike changes.
- Create `spikes/blufi_phase0/wechat_miniprogram/utils/bleWriteQueue.js`: single-flight BLE write queue.
- Create `spikes/blufi_phase0/wechat_miniprogram/utils/successClose.js`: expected-disconnect state helper.
- Create `spikes/blufi_phase0/RESULTS.md`: manual verification matrix and log excerpts.
- Create `tests/test_blufi_phase0_spike.py`: static guards that keep the spike aligned with the design.

### Task 1: Add Phase 0 Static Guards

**Files:**
- Create: `tests/test_blufi_phase0_spike.py`

- [ ] **Step 1: Write the failing guard tests**

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "spikes" / "blufi_phase0"


def test_phase0_firmware_contains_tiny_identity_and_bluetooth_config() -> None:
    tiny_header = SPIKE / "firmware" / "main" / "tiny_blufi_phase0.h"
    tiny_source = SPIKE / "firmware" / "main" / "tiny_blufi_phase0.c"
    sdkconfig_defaults = SPIKE / "firmware" / "sdkconfig.defaults"

    assert tiny_header.exists()
    assert tiny_source.exists()

    source = tiny_source.read_text(encoding="utf-8")
    defaults = sdkconfig_defaults.read_text(encoding="utf-8")

    assert '"tc-s3-"' in source
    assert '"XiaoJiZi-"' in source
    assert "pairing_pin_missing_using_0000" in source
    assert "CONFIG_BT_BLE_BLUFI_ENABLE=y" in defaults
    assert "CONFIG_EXAMPLE_BLUFI_BLE_SMP_ENABLE=y" in defaults


def test_phase0_success_close_handshake_is_client_driven() -> None:
    firmware = (SPIKE / "firmware" / "main" / "blufi_example_main.c").read_text(encoding="utf-8")
    success_close = (SPIKE / "wechat_miniprogram" / "utils" / "successClose.js").read_text(encoding="utf-8")

    assert "PROVISIONING_SUCCESS" in firmware
    assert "tiny_blufi_phase0_send_success_notify" in firmware
    assert "esp_blufi_adv_stop()" in firmware
    assert "esp_blufi_close" not in firmware
    assert "expectedDisconnect" in success_close
    assert "wx.closeBLEConnection" in success_close


def test_phase0_wechat_client_uses_single_flight_ble_write_queue() -> None:
    queue = (SPIKE / "wechat_miniprogram" / "utils" / "bleWriteQueue.js").read_text(encoding="utf-8")

    assert "class BleWriteQueue" in queue
    assert "_writing" in queue
    assert "wx.writeBLECharacteristicValue" in queue
    assert "setTimeout" in queue
    assert "retry" in queue


def test_phase0_manual_results_cover_required_matrix() -> None:
    results = (SPIKE / "RESULTS.md").read_text(encoding="utf-8")

    assert "Android success 1" in results
    assert "Android success 2" in results
    assert "Android success 3" in results
    assert "iPhone success 1" in results
    assert "iPhone success 2" in results
    assert "iPhone success 3" in results
    assert "Wrong password" in results
    assert "Interrupted BLE connection" in results
    assert "COM6" in results
```

- [ ] **Step 2: Run guards to verify they fail**

Run:

```powershell
pytest tests/test_blufi_phase0_spike.py -q
```

Expected: fail with missing `spikes/blufi_phase0` files.

- [ ] **Step 3: Commit the failing tests**

```powershell
git add tests/test_blufi_phase0_spike.py
git commit -m "test: guard blufi phase0 spike"
```

### Task 2: Import The ESP-IDF BluFi Firmware Example

**Files:**
- Create: `spikes/blufi_phase0/firmware/**`
- Create: `spikes/blufi_phase0/README.md`
- Create: `spikes/blufi_phase0/factory_nvs/pairing_pin.csv`
- Modify: `spikes/blufi_phase0/firmware/sdkconfig.defaults`

- [ ] **Step 1: Copy the local ESP-IDF BluFi example**

Run:

```powershell
New-Item -ItemType Directory -Force spikes\blufi_phase0 | Out-Null
Copy-Item -Recurse C:\esp\v5.5.4\esp-idf\examples\bluetooth\blufi spikes\blufi_phase0\firmware
```

Expected: `spikes\blufi_phase0\firmware\main\blufi_example_main.c` exists.

- [ ] **Step 2: Add the Phase 0 README**

Create `spikes/blufi_phase0/README.md`:

```markdown
# Tiny Coffee BluFi Phase 0

This spike verifies WeChat Mini Program BluFi provisioning on the target ESP32-S3 board before product development begins.

Firmware source starts from the ESP-IDF v5.5.4 BluFi example at:

`C:\esp\v5.5.4\esp-idf\examples\bluetooth\blufi`

The ESP-IDF example files keep their original `Unlicense OR CC0-1.0` SPDX headers.

The WeChat reference starts from:

`https://github.com/EspressifApps/ESP-Config-WeChat`

That repository declares `ISC` in `package.json`; preserve that metadata when copying the reference.

Manual success requires:

- Three successful Android provisioning runs.
- Three successful iPhone provisioning runs.
- One wrong-password failure with a visible retryable error.
- One interrupted BLE connection failure with a visible retryable error.
```

- [ ] **Step 3: Add a repeatable factory PIN NVS input**

Create `spikes/blufi_phase0/factory_nvs/pairing_pin.csv`:

```csv
key,type,encoding,value
factory,namespace,,
pairing_pin,data,u16,1234
```

- [ ] **Step 4: Enable BluFi SMP in `sdkconfig.defaults`**

Append to `spikes/blufi_phase0/firmware/sdkconfig.defaults`:

```ini

# Tiny Coffee Phase 0 hardening
CONFIG_EXAMPLE_BLUFI_BLE_SMP_ENABLE=y
CONFIG_BT_BLE_SMP_ENABLE=y
```

- [ ] **Step 5: Run guards and verify the expected remaining failures**

Run:

```powershell
pytest tests/test_blufi_phase0_spike.py -q
```

Expected: still fails because Tiny helper files, mini program queue, and results file are not created.

- [ ] **Step 6: Commit the imported firmware baseline**

```powershell
git add spikes/blufi_phase0
git commit -m "chore: import blufi phase0 baseline"
```

### Task 3: Add Tiny Coffee Firmware Identity, PIN, And Success Notify

**Files:**
- Create: `spikes/blufi_phase0/firmware/main/tiny_blufi_phase0.h`
- Create: `spikes/blufi_phase0/firmware/main/tiny_blufi_phase0.c`
- Modify: `spikes/blufi_phase0/firmware/main/CMakeLists.txt`
- Modify: `spikes/blufi_phase0/firmware/main/blufi_init.c`
- Modify: `spikes/blufi_phase0/firmware/main/blufi_example_main.c`

- [ ] **Step 1: Create `tiny_blufi_phase0.h`**

```c
#pragma once

#include <stdint.h>

#include "esp_err.h"

#define TINY_BLUFI_PHASE0_PIN_MISSING_LOG "pairing_pin_missing_using_0000"

esp_err_t tiny_blufi_phase0_init(void);
const char *tiny_blufi_phase0_device_id(void);
const char *tiny_blufi_phase0_ble_name(void);
uint16_t tiny_blufi_phase0_pairing_pin(void);
esp_err_t tiny_blufi_phase0_send_success_notify(const char *firmware_version);
```

- [ ] **Step 2: Create `tiny_blufi_phase0.c`**

```c
#include "tiny_blufi_phase0.h"

#include <stdio.h>
#include <string.h>

#include "esp_blufi_api.h"
#include "esp_efuse.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "nvs.h"

static const char *TAG = "tiny_blufi_phase0";

static char s_device_id[32];
static char s_ble_name[32];
static uint16_t s_pairing_pin = 0;

static void tiny_blufi_phase0_build_ids(const uint8_t mac[6])
{
    snprintf(s_device_id,
             sizeof(s_device_id),
             "tc-s3-%02x%02x%02x%02x%02x%02x",
             mac[0],
             mac[1],
             mac[2],
             mac[3],
             mac[4],
             mac[5]);
    snprintf(s_ble_name, sizeof(s_ble_name), "XiaoJiZi-%02x%02x", mac[4], mac[5]);
}

static uint16_t tiny_blufi_phase0_load_pairing_pin(void)
{
    nvs_handle_t handle;
    uint16_t pin = 0;

    esp_err_t ret = nvs_open("factory", NVS_READONLY, &handle);
    if (ret == ESP_OK) {
        ret = nvs_get_u16(handle, "pairing_pin", &pin);
        nvs_close(handle);
    }

    if (ret != ESP_OK || pin > 9999) {
        ESP_LOGW(TAG, TINY_BLUFI_PHASE0_PIN_MISSING_LOG);
        return 0;
    }

    return pin;
}

esp_err_t tiny_blufi_phase0_init(void)
{
    uint8_t mac[6] = {0};
    esp_err_t ret = esp_efuse_mac_get_default(mac);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "phase0_mac_read_failed err=%s", esp_err_to_name(ret));
        return ret;
    }

    tiny_blufi_phase0_build_ids(mac);
    s_pairing_pin = tiny_blufi_phase0_load_pairing_pin();

    ESP_LOGI(TAG, "phase0_device_id=%s", s_device_id);
    ESP_LOGI(TAG, "phase0_ble_name=%s", s_ble_name);
    ESP_LOGI(TAG, "phase0_pairing_pin_loaded=%d", s_pairing_pin != 0);
    return ESP_OK;
}

const char *tiny_blufi_phase0_device_id(void)
{
    return s_device_id;
}

const char *tiny_blufi_phase0_ble_name(void)
{
    return s_ble_name;
}

uint16_t tiny_blufi_phase0_pairing_pin(void)
{
    return s_pairing_pin;
}

esp_err_t tiny_blufi_phase0_send_success_notify(const char *firmware_version)
{
    char payload[160];
    int written = snprintf(payload,
                           sizeof(payload),
                           "{\"type\":\"PROVISIONING_SUCCESS\",\"device_id\":\"%s\",\"firmware_version\":\"%s\"}",
                           s_device_id,
                           firmware_version);
    if (written <= 0 || written >= (int)sizeof(payload)) {
        return ESP_ERR_INVALID_SIZE;
    }

    ESP_LOGI(TAG, "phase0_notify_success payload=%s", payload);
    return esp_blufi_send_custom_data((uint8_t *)payload, (uint32_t)written);
}
```

- [ ] **Step 3: Compile the helper file**

Modify `spikes/blufi_phase0/firmware/main/CMakeLists.txt` so the `SRCS` list includes `tiny_blufi_phase0.c`:

```cmake
idf_component_register(SRCS "blufi_example_main.c"
                            "blufi_security.c"
                            "blufi_init.c"
                            "tiny_blufi_phase0.c"
                    INCLUDE_DIRS ".")
```

- [ ] **Step 4: Use the Tiny Coffee BLE device name**

In `spikes/blufi_phase0/firmware/main/blufi_init.c`, add:

```c
#include "tiny_blufi_phase0.h"
```

Replace both uses of `BLUFI_DEVICE_NAME` with `tiny_blufi_phase0_ble_name()`.

Expected replacements:

```c
ret = esp_ble_gap_set_device_name(tiny_blufi_phase0_ble_name());
```

```c
rc = ble_svc_gap_device_name_set(tiny_blufi_phase0_ble_name());
```

- [ ] **Step 5: Initialize Tiny Coffee identity in app startup**

In `spikes/blufi_phase0/firmware/main/blufi_example_main.c`, add:

```c
#include "tiny_blufi_phase0.h"
```

At the start of `app_main`, after `nvs_flash_init()` succeeds and before BluFi host init, add:

```c
ESP_ERROR_CHECK(tiny_blufi_phase0_init());
```

- [ ] **Step 6: Send success notify before client-driven close**

In `spikes/blufi_phase0/firmware/main/blufi_example_main.c`, in the `IP_EVENT_STA_GOT_IP` branch after `esp_blufi_send_wifi_conn_report(...)`, add:

```c
esp_err_t notify_ret = tiny_blufi_phase0_send_success_notify("phase0");
if (notify_ret != ESP_OK) {
    BLUFI_ERROR("phase0_success_notify_failed err=%s\n", esp_err_to_name(notify_ret));
}
esp_blufi_adv_stop();
BLUFI_INFO("phase0_success_waiting_for_client_close\n");
```

Do not add any success-path call that actively closes the BLE connection.

- [ ] **Step 7: Run guards**

Run:

```powershell
pytest tests/test_blufi_phase0_spike.py::test_phase0_firmware_contains_tiny_identity_and_bluetooth_config tests/test_blufi_phase0_spike.py::test_phase0_success_close_handshake_is_client_driven -q
```

Expected: first firmware guard passes; success handshake guard may still fail until the mini program helper exists.

- [ ] **Step 8: Commit firmware Tiny Coffee changes**

```powershell
git add spikes/blufi_phase0/firmware tests/test_blufi_phase0_spike.py
git commit -m "feat: add blufi phase0 firmware identity"
```

### Task 4: Generate And Flash Factory PIN NVS

**Files:**
- Modify: `spikes/blufi_phase0/README.md`
- Create: `spikes/blufi_phase0/factory_nvs/pairing_pin.bin`

- [ ] **Step 1: Generate the NVS image**

Run:

```powershell
python C:\esp\v5.5.4\esp-idf\components\nvs_flash\nvs_partition_generator\nvs_partition_gen.py generate spikes\blufi_phase0\factory_nvs\pairing_pin.csv spikes\blufi_phase0\factory_nvs\pairing_pin.bin 0x6000
```

Expected: command exits 0 and creates `spikes\blufi_phase0\factory_nvs\pairing_pin.bin`.

- [ ] **Step 2: Document the factory write command**

Append to `spikes/blufi_phase0/README.md`:

````markdown
## Factory Pairing PIN

The default NVS partition stores namespace `factory`, key `pairing_pin`, type `u16`.

Generate the NVS image:

```powershell
python C:\esp\v5.5.4\esp-idf\components\nvs_flash\nvs_partition_generator\nvs_partition_gen.py generate spikes\blufi_phase0\factory_nvs\pairing_pin.csv spikes\blufi_phase0\factory_nvs\pairing_pin.bin 0x6000
```

Flash the generated NVS image to the default NVS offset:

```powershell
python -m esptool --chip esp32s3 -p COM6 write_flash 0x9000 spikes\blufi_phase0\factory_nvs\pairing_pin.bin
```

If firmware logs `pairing_pin_missing_using_0000`, lab provisioning can continue with PIN `0000`, but production test fails that unit.
````

- [ ] **Step 3: Commit NVS tooling docs and generated image**

```powershell
git add spikes/blufi_phase0/factory_nvs spikes/blufi_phase0/README.md
git commit -m "chore: add blufi phase0 pairing pin nvs"
```

### Task 5: Import The WeChat BluFi Reference And Add Client-Side Queueing

**Files:**
- Create: `spikes/blufi_phase0/wechat_miniprogram/**`
- Create: `spikes/blufi_phase0/wechat_miniprogram/utils/bleWriteQueue.js`
- Create: `spikes/blufi_phase0/wechat_miniprogram/utils/successClose.js`
- Modify: `spikes/blufi_phase0/wechat_miniprogram/pages/blueDevices/blueDevices.js`
- Modify: `spikes/blufi_phase0/wechat_miniprogram/pages/blueConnect/blueConnect.js`

- [ ] **Step 1: Copy Espressif's WeChat reference**

Run:

```powershell
git clone --depth 1 https://github.com/EspressifApps/ESP-Config-WeChat.git C:\tmp\esp-config-wechat-phase0
New-Item -ItemType Directory -Force spikes\blufi_phase0\wechat_miniprogram | Out-Null
Copy-Item -Recurse C:\tmp\esp-config-wechat-phase0\* spikes\blufi_phase0\wechat_miniprogram
Remove-Item -Recurse -Force spikes\blufi_phase0\wechat_miniprogram\.git
```

Expected: `spikes\blufi_phase0\wechat_miniprogram\pages\blueConnect\blueConnect.js` exists and `package.json` contains `"license": "ISC"`.

- [ ] **Step 2: Add single-flight BLE write queue**

Create `spikes/blufi_phase0/wechat_miniprogram/utils/bleWriteQueue.js`:

```javascript
class BleWriteQueue {
  constructor(wxApi, options) {
    this.wx = wxApi || wx
    this.queue = []
    this._writing = false
    this.timeoutMs = (options && options.timeoutMs) || 3000
    this.retry = (options && options.retry) || 2
  }

  write(params) {
    return new Promise((resolve, reject) => {
      this.queue.push({ params, resolve, reject, attempt: 0 })
      this._drain()
    })
  }

  clear() {
    this.queue = []
    this._writing = false
  }

  _drain() {
    if (this._writing || this.queue.length === 0) {
      return
    }

    const item = this.queue[0]
    this._writing = true
    let settled = false

    const timer = setTimeout(() => {
      if (settled) {
        return
      }
      settled = true
      this._finish(item, new Error('write_timeout'))
    }, this.timeoutMs)

    this.wx.writeBLECharacteristicValue({
      ...item.params,
      success: (res) => {
        if (settled) {
          return
        }
        settled = true
        clearTimeout(timer)
        this._finish(item, null, res)
      },
      fail: (err) => {
        if (settled) {
          return
        }
        settled = true
        clearTimeout(timer)
        this._finish(item, err || new Error('write_failed'))
      },
    })
  }

  _finish(item, err, res) {
    this.queue.shift()
    this._writing = false

    if (err && item.attempt < this.retry) {
      item.attempt += 1
      this.queue.unshift(item)
      setTimeout(() => this._drain(), 150 * item.attempt)
      return
    }

    if (err) {
      item.reject(err)
    } else {
      item.resolve(res)
    }
    this._drain()
  }
}

module.exports = BleWriteQueue
```

- [ ] **Step 3: Add success close helper**

Create `spikes/blufi_phase0/wechat_miniprogram/utils/successClose.js`:

```javascript
function createSuccessClose(wxApi) {
  const api = wxApi || wx
  let expectedDisconnect = false
  let terminalSuccess = false

  return {
    markSuccess() {
      terminalSuccess = true
      expectedDisconnect = true
    },
    isExpectedDisconnect() {
      return expectedDisconnect || terminalSuccess
    },
    close(deviceId) {
      expectedDisconnect = true
      return new Promise((resolve) => {
        api.closeBLEConnection({
          deviceId,
          success: resolve,
          fail: resolve,
        })
      })
    },
    reset() {
      expectedDisconnect = false
      terminalSuccess = false
    },
  }
}

module.exports = createSuccessClose
```

- [ ] **Step 4: Filter devices by Tiny Coffee BLE prefix**

In `spikes/blufi_phase0/wechat_miniprogram/pages/blueDevices/blueDevices.js`, replace the BluFi prefix filter with `XiaoJiZi-`.

Expected line:

```javascript
const filtered = util.filterDevice(devices, 'name', { prefix: 'XiaoJiZi-' })
```

If that exact local variable does not exist after import, keep the existing file structure and pass `{ prefix: 'XiaoJiZi-' }` into the existing `util.filterDevice(...)` call.

- [ ] **Step 5: Use queue and success close in `blueConnect.js`**

At the top of `spikes/blufi_phase0/wechat_miniprogram/pages/blueConnect/blueConnect.js`, add:

```javascript
const BleWriteQueue = require('../../utils/bleWriteQueue.js')
const createSuccessClose = require('../../utils/successClose.js')
```

In page `data`, add:

```javascript
phase0Success: false,
phase0DeviceId: '',
```

In `onLoad`, initialize helpers:

```javascript
this.writeQueue = new BleWriteQueue(wx, { timeoutMs: 3000, retry: 2 })
this.successClose = createSuccessClose(wx)
```

In each function that calls `wx.writeBLECharacteristicValue`, replace the direct call with:

```javascript
this.writeQueue.write({
  deviceId: deviceId,
  serviceId: serviceId,
  characteristicId: characteristicId,
  value: typedArray.buffer,
}).then(() => {
  // Keep the existing success branch body here.
}).catch(() => {
  self.setFailProcess(true, util.descFailList[4])
})
```

In the notify handler, after converting custom data to string, add:

```javascript
if (text.indexOf('PROVISIONING_SUCCESS') !== -1) {
  const payload = JSON.parse(text)
  self.successClose.markSuccess()
  self.setData({
    phase0Success: true,
    phase0DeviceId: payload.device_id || '',
    desc: '配网成功',
  })
  self.successClose.close(self.data.deviceId)
  return
}
```

In `wx.onBLEConnectionStateChange`, add:

```javascript
if (!res.connected && self.successClose && self.successClose.isExpectedDisconnect()) {
  return
}
```

- [ ] **Step 6: Run guards for mini program static behavior**

Run:

```powershell
pytest tests/test_blufi_phase0_spike.py::test_phase0_success_close_handshake_is_client_driven tests/test_blufi_phase0_spike.py::test_phase0_wechat_client_uses_single_flight_ble_write_queue -q
```

Expected: both pass.

- [ ] **Step 7: Commit mini program spike changes**

```powershell
git add spikes/blufi_phase0/wechat_miniprogram tests/test_blufi_phase0_spike.py
git commit -m "feat: add blufi phase0 wechat client"
```

### Task 6: Build And Flash Phase 0 Firmware On COM6

**Files:**
- Modify: `spikes/blufi_phase0/RESULTS.md`

- [ ] **Step 1: Build the firmware**

Run:

```powershell
cd C:\esp_projects\20260701_Tiny_Machine_Robot_bringup\spikes\blufi_phase0\firmware
. C:\esp\v5.5.4\esp-idf\export.ps1
idf.py set-target esp32s3
idf.py build
```

Expected: build exits 0.

- [ ] **Step 2: Flash firmware and factory NVS to COM6**

Run:

```powershell
cd C:\esp_projects\20260701_Tiny_Machine_Robot_bringup\spikes\blufi_phase0\firmware
. C:\esp\v5.5.4\esp-idf\export.ps1
idf.py -p COM6 flash
python C:\esp\v5.5.4\esp-idf\components\nvs_flash\nvs_partition_generator\nvs_partition_gen.py generate ..\factory_nvs\pairing_pin.csv ..\factory_nvs\pairing_pin.bin 0x6000
python -m esptool --chip esp32s3 -p COM6 write_flash 0x9000 ..\factory_nvs\pairing_pin.bin
```

Expected: flash exits 0 and no `pairing_pin_missing_using_0000` appears after reboot.

- [ ] **Step 3: Capture boot logs**

Run:

```powershell
idf.py -p COM6 monitor
```

Expected log snippets:

```text
phase0_device_id=tc-s3-
phase0_ble_name=XiaoJiZi-
phase0_pairing_pin_loaded=1
BLUFI init finish
```

- [ ] **Step 4: Create initial results file**

Create `spikes/blufi_phase0/RESULTS.md`:

````markdown
# Tiny Coffee BluFi Phase 0 Results

Hardware: ESP32-S3 target board
Serial: COM6
Firmware app: `spikes/blufi_phase0/firmware`
Mini program: `spikes/blufi_phase0/wechat_miniprogram`
Pairing PIN source: default NVS namespace `factory`, key `pairing_pin`

## Boot Log

```text
phase0_device_id=tc-s3-
phase0_ble_name=XiaoJiZi-
phase0_pairing_pin_loaded=1
BLUFI init finish
```

## Verification Matrix

| Case | Phone | Wi-Fi SSID | Result | Notes |
| --- | --- | --- | --- | --- |
| Android success 1 | Android | GMT-VIP | Not run | |
| Android success 2 | Android | GMT-VIP | Not run | |
| Android success 3 | Android | GMT-VIP | Not run | |
| iPhone success 1 | iPhone | GMT-VIP | Not run | |
| iPhone success 2 | iPhone | GMT-VIP | Not run | |
| iPhone success 3 | iPhone | GMT-VIP | Not run | |
| Wrong password | Android or iPhone | GMT-VIP | Not run | |
| Interrupted BLE connection | Android or iPhone | GMT-VIP | Not run | |

## Exit Criteria

- Android success 1, 2, and 3 are `Pass`.
- iPhone success 1, 2, and 3 are `Pass`.
- Wrong password returns a visible retryable error.
- Interrupted BLE connection returns a visible retryable error.
- `PROVISIONING_SUCCESS` is received before the mini program closes BLE.
- The success close handshake does not show a transient Bluetooth disconnected error.
````

- [ ] **Step 5: Run guards**

Run:

```powershell
pytest tests/test_blufi_phase0_spike.py -q
```

Expected: static guards pass. Manual matrix still contains `Not run`, so the spike is not accepted until Task 7.

- [ ] **Step 6: Commit build/run scaffolding**

```powershell
git add spikes/blufi_phase0/RESULTS.md
git commit -m "docs: add blufi phase0 result matrix"
```

### Task 7: Run Manual Phone Matrix And Close Phase 0

**Files:**
- Modify: `spikes/blufi_phase0/RESULTS.md`

- [ ] **Step 1: Open the WeChat mini program in DevTools**

Open `spikes/blufi_phase0/wechat_miniprogram` in WeChat DevTools.

Expected: project loads and shows the BluFi flow.

- [ ] **Step 2: Run three Android success attempts**

For each Android run:

1. Reboot the board or restart the provisioning window.
2. Scan for `XiaoJiZi-xxxx`.
3. Enter SSID `GMT-VIP`, password `gmt12345678`, and PIN `1234`.
4. Confirm the mini program receives `PROVISIONING_SUCCESS`.
5. Confirm the success page appears before BLE closes.

Update `RESULTS.md` rows `Android success 1`, `Android success 2`, and `Android success 3` to `Pass` with short notes.

- [ ] **Step 3: Run three iPhone success attempts**

Repeat the same flow on iPhone and update `RESULTS.md` rows `iPhone success 1`, `iPhone success 2`, and `iPhone success 3` to `Pass`.

- [ ] **Step 4: Run wrong-password failure**

Enter SSID `GMT-VIP` and an intentionally wrong password.

Expected: mini program shows a retryable wrong-password or Wi-Fi join failure state, and the board remains retryable within the active provisioning window.

Update `RESULTS.md` row `Wrong password` to `Pass`.

- [ ] **Step 5: Run interrupted BLE failure**

Start provisioning, then turn Bluetooth off on the phone or move out of range before success.

Expected: mini program shows retryable connection-lost error because `PROVISIONING_SUCCESS` was not received.

Update `RESULTS.md` row `Interrupted BLE connection` to `Pass`.

- [ ] **Step 6: Run full verification**

Run:

```powershell
pytest tests/test_blufi_phase0_spike.py -q
cd C:\esp_projects\20260701_Tiny_Machine_Robot_bringup\spikes\blufi_phase0\firmware
. C:\esp\v5.5.4\esp-idf\export.ps1
idf.py build
```

Expected: pytest exits 0 and firmware build exits 0.

- [ ] **Step 7: Commit Phase 0 results**

```powershell
git add spikes/blufi_phase0 tests/test_blufi_phase0_spike.py
git commit -m "test: record blufi phase0 hardware results"
```

## Self-Review Checklist

- The plan implements only Phase 0 BluFi compatibility and does not start backend or product page work.
- Static guards cover firmware identity, Bluetooth config, success close handshake, BLE write queue, and manual result matrix.
- Firmware uses `tc-s3-<mac>` and `XiaoJiZi-xxxx`.
- Production PIN path uses default NVS partition, namespace `factory`, key `pairing_pin`, type `u16`.
- Missing PIN logs `pairing_pin_missing_using_0000`.
- Success path sends `PROVISIONING_SUCCESS`, stops advertising, and waits for the mini program to close BLE.
- The mini program suppresses expected disconnect only after terminal success.
- Manual exit criteria match the approved design: three Android successes, three iPhone successes, wrong password, and interrupted BLE.
