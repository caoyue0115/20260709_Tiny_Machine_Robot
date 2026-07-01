from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_firmware_keeps_xiaoming_wake_word_and_volcengine_asr_default() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")

    assert '#define DEMO_WAKE_WORD_TEXT "小明同学"' in config
    assert '#define V5_OPUS_UPLINK_ASR_PROVIDER "volcengine"' in config


def test_ota_is_inactive_by_default() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")

    assert "#define DEMO_OTA_MANIFEST_DRY_RUN_ENABLED 1" in config
    assert "#define DEMO_OTA_PARTITION_WRITE_ENABLED 0" in config
    assert "#define DEMO_OTA_BOOT_SWITCH_ENABLED 0" in config
    assert "#define DEMO_OTA_ROLLBACK_VALIDATION_ENABLED 0" in config


def test_cmake_accepts_local_string_macros_without_committing_values() -> None:
    cmake = (ROOT / "esp_idf_demo" / "main" / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "DEMO_LOCAL_STRING_DEFINITIONS" in cmake
    assert "target_compile_definitions(${COMPONENT_LIB} PRIVATE" in cmake
