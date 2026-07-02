from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _assert_guarded_define(config: str, name: str, value: str) -> None:
    assert f"#ifndef {name}\n#define {name} {value}\n#endif" in config


def test_firmware_keeps_xiaoming_wake_word_and_volcengine_asr_default() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")

    assert '#define DEMO_WAKE_WORD_TEXT "小明同学"' in config
    assert '#define V5_OPUS_UPLINK_ASR_PROVIDER "volcengine"' in config


def test_ota_is_inactive_by_default() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")

    _assert_guarded_define(config, "DEMO_OTA_MANIFEST_DRY_RUN_ENABLED", "1")
    _assert_guarded_define(config, "DEMO_OTA_PARTITION_WRITE_ENABLED", "0")
    _assert_guarded_define(config, "DEMO_OTA_BOOT_SWITCH_ENABLED", "0")
    _assert_guarded_define(config, "DEMO_OTA_ROLLBACK_VALIDATION_ENABLED", "0")


def test_cmake_accepts_local_string_macros_without_committing_values() -> None:
    cmake = (ROOT / "esp_idf_demo" / "main" / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "DEMO_LOCAL_STRING_DEFINITIONS" in cmake
    assert "DEMO_WIFI_SSID" in cmake
    assert "DEMO_WIFI_PASSWORD" in cmake
    assert "DEMO_SERVER_BASE_URL" in cmake
    assert "DEMO_DEVICE_ID" in cmake
    assert 'target_compile_definitions(${COMPONENT_LIB} PRIVATE ${name}="${${name}}")' in cmake


def test_default_firmware_build_uses_lowcost_v1_audio_profile() -> None:
    defaults = (ROOT / "esp_idf_demo" / "sdkconfig.defaults").read_text(encoding="utf-8")

    assert "CONFIG_DEMO_TARGET_PROFILE_VOCAT_LOWCOST_16M8M=y" in defaults
    assert "CONFIG_DEMO_AUDIO_PCB_ESP_VOCAT_V1_0=y" in defaults
