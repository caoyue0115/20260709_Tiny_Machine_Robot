from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _assert_guarded_define(config: str, name: str, value: str) -> None:
    assert f"#ifndef {name}\n#define {name} {value}\n#endif" in config


def _guarded_define_int(config: str, name: str) -> int:
    prefix = f"#ifndef {name}\n#define {name} "
    start = config.index(prefix) + len(prefix)
    end = config.index("\n#endif", start)
    return int(config[start:end].strip())


def test_firmware_keeps_xiaoming_wake_word_and_volcengine_asr_default() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")

    assert '#define DEMO_WAKE_WORD_TEXT "小明同学"' in config
    assert '#define V5_OPUS_UPLINK_ASR_PROVIDER "volcengine"' in config


def test_ota_is_inactive_by_default() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")

    _assert_guarded_define(config, "DEMO_OTA_MANIFEST_DRY_RUN_ENABLED", "0")
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


def test_realtime_downlink_queue_timeout_allows_playback_backpressure() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")
    audio_out = (ROOT / "esp_idf_demo" / "main" / "audio_out.c").read_text(encoding="utf-8")

    queue_timeout_ms = _guarded_define_int(config, "DEMO_REALTIME_AUDIO_QUEUE_SEND_TIMEOUT_MS")
    jitter_prebuffer_bytes = _guarded_define_int(config, "DEMO_REALTIME_AUDIO_JITTER_PREBUFFER_BYTES")
    byte_rate = 16000 * 1 * 2
    prebuffer_ms = jitter_prebuffer_bytes * 1000 // byte_rate

    assert queue_timeout_ms >= prebuffer_ms * 4
    assert "pdMS_TO_TICKS(DEMO_REALTIME_AUDIO_QUEUE_SEND_TIMEOUT_MS)" in audio_out


def test_waiting_speech_vad_threshold_ignores_observed_silence_noise() -> None:
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")
    audio_in = (ROOT / "esp_idf_demo" / "main" / "audio_in.c").read_text(encoding="utf-8")

    waiting_threshold = _guarded_define_int(config, "DEMO_WAITING_SPEECH_START_THRESHOLD")
    record_threshold = _guarded_define_int(config, "DEMO_RECORD_VAD_START_THRESHOLD")

    assert waiting_threshold >= 800
    assert record_threshold == 450
    assert "chunk_level >= DEMO_WAITING_SPEECH_START_THRESHOLD" in audio_in


def test_multinet_keeps_start_mode_repeat_commands_but_not_exit_commands() -> None:
    command_source = (ROOT / "esp_idf_demo" / "main" / "local_command_service.c").read_text(
        encoding="utf-8"
    )
    command_header = (ROOT / "esp_idf_demo" / "main" / "local_command_service.h").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")

    assert "{130," not in command_source
    assert "{131," not in command_source
    assert "LOCAL_COMMAND_KIND_IDIOM_EXIT" not in command_source
    assert "LOCAL_COMMAND_KIND_IDIOM_EXIT" not in command_header
    expected_repeat_commands = {
        140: ("wo mei ting qing", "我没听清"),
        141: ("wo mei ting dao", "我没听到"),
        142: ("zai shuo yi bian", "再说一遍"),
        143: ("chong fu yi bian", "重复一遍"),
        144: ("gang cai shi shen me", "刚才是什么"),
    }
    for command_id, (pinyin, text) in expected_repeat_commands.items():
        assert (
            f'{{{command_id}, "{pinyin}", "{text}", LOCAL_COMMAND_KIND_IDIOM_REPEAT}}'
            in command_source
        )
    assert "LOCAL_COMMAND_KIND_IDIOM_REPEAT" in command_header
    assert (
        "kind == LOCAL_COMMAND_KIND_IDIOM_MODE || kind == LOCAL_COMMAND_KIND_IDIOM_REPEAT"
        in main
    )


def test_game_capture_uses_real_200ms_preroll_and_200ms_trailing_silence() -> None:
    audio_header = (ROOT / "esp_idf_demo" / "main" / "audio_in.h").read_text(encoding="utf-8")
    audio_source = (ROOT / "esp_idf_demo" / "main" / "audio_in.c").read_text(encoding="utf-8")

    assert "#define AUDIO_IN_GAME_PREROLL_MS 200" in audio_header
    assert "#define AUDIO_IN_GAME_TRAILING_SILENCE_MS 200" in audio_header
    assert "audio_in_wait_for_game_speech_start" in audio_header
    assert "audio_in_stream_game_after_speech_start" in audio_header
    assert "game_preroll_ring" in audio_source
    assert "memcpy(game_preroll_ring" in audio_source
    assert "AUDIO_IN_GAME_PREROLL_BYTES" in audio_source
    assert "AUDIO_IN_GAME_TRAILING_SILENCE_BYTES" in audio_source
    assert "calloc(1, AUDIO_IN_GAME_PREROLL_BYTES)" not in audio_source


def test_game_cloud_client_keeps_socket_across_turns_and_matches_turn_id() -> None:
    cloud_header = (ROOT / "esp_idf_demo" / "main" / "cloud_client.h").read_text(encoding="utf-8")
    cloud_source = (ROOT / "esp_idf_demo" / "main" / "cloud_client.c").read_text(encoding="utf-8")

    for api_name in (
        "cloud_client_idiom_game_connect",
        "cloud_client_idiom_game_begin_turn",
        "cloud_client_idiom_game_send_pcm",
        "cloud_client_idiom_game_finish_turn",
        "cloud_client_idiom_game_close",
    ):
        assert api_name in cloud_header
        assert api_name in cloud_source
    assert "api/v5/realtime/idiom-game/opus-stream" in cloud_source
    assert '\\\"type\\\":\\\"utterance_start\\\"' in cloud_source
    assert '\\\"type\\\":\\\"utterance_end\\\"' in cloud_source
    assert '\\\"turn_id\\\"' in cloud_source
    assert "incoming_turn_id" in cloud_source
    assert "stale_turn_id" in cloud_source
    assert "char skill_name[32]" in cloud_header
    assert "bool skill_active" in cloud_header
    assert "bool end_skill_state" in cloud_header
    finish_body = cloud_source.split("esp_err_t cloud_client_idiom_game_finish_turn", 1)[1].split(
        "void cloud_client_idiom_game_close", 1
    )[0]
    assert "cloud_client_opus_uplink_abort" not in finish_body


def test_main_has_wake_free_idiom_game_state_machine_and_echo_guard() -> None:
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")

    for state in (
        "APP_IDIOM_GAME_SOCKET_IDLE",
        "APP_IDIOM_GAME_PLAYBACK",
        "APP_IDIOM_GAME_ECHO_GUARD",
        "APP_IDIOM_GAME_VAD_ARMED",
        "APP_IDIOM_GAME_UPLOADING",
        "APP_IDIOM_GAME_WAITING_REPLY",
    ):
        assert state in main
    assert "#define APP_IDIOM_GAME_ECHO_GUARD_MS 200" in main
    assert "app_run_idiom_game_loop" in main
    assert "audio_in_wait_for_game_speech_start" in main
    assert "cloud_client_idiom_game_begin_turn" in main
    assert "cloud_client_idiom_game_finish_turn" in main
    assert "realtime_session.end_skill_state" in main
    assert "realtime_session.skill_active" in main
    assert 'strcmp(realtime_session.skill_name, "idiom_game") == 0' in main
    assert "s_local_idiom_context_until_us = 0" in main
    timeout_branch = main.split("if (ret == DEMO_AUDIO_IN_ERR_WAIT_TIMEOUT)", 1)[1].split(
        "if (ret != ESP_OK)", 1
    )[0]
    assert "ret = ESP_OK" in timeout_branch


def test_game_multinet_hit_uses_text_session_before_cloud_asr_start() -> None:
    local_header = (ROOT / "esp_idf_demo" / "main" / "local_command_service.h").read_text(
        encoding="utf-8"
    )
    local_source = (ROOT / "esp_idf_demo" / "main" / "local_command_service.c").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")

    assert "bool timed_out" in local_header
    assert "ESP_MN_STATE_TIMEOUT" in local_source
    assert "app_idiom_game_capture_sink" in main
    capture_sink = main.split("static esp_err_t app_idiom_game_capture_sink", 1)[1].split(
        "static esp_err_t app_play_idiom_game_audio", 1
    )[0]
    assert capture_sink.index("local_command_service_feed") < capture_sink.index(
        "app_idiom_game_start_cloud_turn"
    )
    assert "APP_LOCAL_COMMAND_INTERCEPT_REQUESTED" in capture_sink
    start_cloud = main.split("static esp_err_t app_idiom_game_start_cloud_turn", 1)[1].split(
        "static esp_err_t app_idiom_game_capture_sink", 1
    )[0]
    assert "cloud_client_idiom_game_begin_turn" in start_cloud
    game_loop = main.split("static esp_err_t app_run_idiom_game_loop", 1)[1].split(
        "static esp_err_t run_trigger_pipeline", 1
    )[0]
    assert "app_local_command_submit_text_session" in game_loop
    assert "cloud_client_submit_realtime_session" not in game_loop
