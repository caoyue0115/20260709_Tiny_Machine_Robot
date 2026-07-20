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
    config = (ROOT / "esp_idf_demo" / "main" / "config.h").read_text(encoding="utf-8")

    assert "#define AUDIO_IN_GAME_PREROLL_MS 200" in audio_header
    assert "#define AUDIO_IN_GAME_TRAILING_SILENCE_MS 200" in audio_header
    assert "audio_in_wait_for_game_speech_start" in audio_header
    assert "audio_in_stream_game_after_speech_start" in audio_header
    assert "game_preroll_ring" in audio_source
    assert "memcpy(game_preroll_ring" in audio_source
    assert "AUDIO_IN_GAME_PREROLL_BYTES" in audio_source
    assert "AUDIO_IN_GAME_TRAILING_SILENCE_BYTES" in audio_source
    assert "calloc(1, AUDIO_IN_GAME_PREROLL_BYTES)" not in audio_source
    assert "#define DEMO_RECORD_DURATION_SEC  4" in config

    stream_body = audio_source.split(
        "esp_err_t audio_in_stream_game_after_speech_start", 1
    )[1].split("void audio_in_deinit", 1)[0]
    assert "pcm_bytes < DEMO_AUDIO_BUFFER_BYTES" in stream_body
    assert "trailing_silence_bytes >= AUDIO_IN_GAME_TRAILING_SILENCE_BYTES" in stream_body


def test_game_vad_waits_for_mic_settle_and_requires_consecutive_speech() -> None:
    audio_header = (ROOT / "esp_idf_demo" / "main" / "audio_in.h").read_text(
        encoding="utf-8"
    )
    audio_source = (ROOT / "esp_idf_demo" / "main" / "audio_in.c").read_text(
        encoding="utf-8"
    )
    wait_body = audio_source.split(
        "esp_err_t audio_in_wait_for_game_speech_start", 1
    )[1].split("esp_err_t audio_in_record_after_speech_start", 1)[0]

    assert "armed_at_us" in wait_body
    assert "DEMO_WAITING_SPEECH_ARM_MS" in wait_body
    assert wait_body.index("audio_in_game_preroll_ring_write") < wait_body.index(
        "now_us < armed_at_us"
    )
    first_armed_branch = wait_body.split("if (!armed_logged)", 1)[1].split(
        "if (chunk_level < DEMO_WAITING_SPEECH_START_THRESHOLD)", 1
    )[0]
    assert "continue" in first_armed_branch
    assert "hold_bytes += DEMO_AUDIO_CHUNK_BYTES" in wait_body
    assert "hold_bytes = 0" in wait_body
    assert "hold_bytes < DEMO_SPEECH_START_HOLD_BYTES" in wait_body
    assert '"stage=idiom_game_waiting_speech event=armed' in wait_body
    assert '"stage=idiom_game_waiting_speech event=speech_detected' in wait_body
    assert '"stage=idiom_game_waiting_speech event=timeout' in wait_body
    wait_declaration = audio_header.split(
        "esp_err_t audio_in_wait_for_game_speech_start", 1
    )[1].split(");", 1)[0]
    assert "uint32_t timeout_ms" in wait_declaration
    assert "timeout_ms == 0" in wait_body
    assert "(int64_t)timeout_ms * 1000" in wait_body


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
    assert "char turn_outcome[16]" in cloud_header
    assert "bool skill_active" in cloud_header
    assert "bool end_skill_state" in cloud_header
    done_handler = cloud_source.split('strcmp(type, "done") == 0', 1)[1].split(
        'strcmp(type, "idle_exit_ack") == 0', 1
    )[0]
    assert '"turn_outcome"' in done_handler
    assert "uplink->session.turn_outcome" in done_handler
    assert "sizeof(uplink->session.turn_outcome)" in done_handler
    finish_body = cloud_source.split("esp_err_t cloud_client_idiom_game_finish_turn", 1)[1].split(
        "void cloud_client_idiom_game_close", 1
    )[0]
    assert "cloud_client_opus_uplink_abort" not in finish_body


def test_recoverable_game_turn_error_uses_feedback_policy_without_reconnecting() -> None:
    cloud_header = (ROOT / "esp_idf_demo" / "main" / "cloud_client.h").read_text(
        encoding="utf-8"
    )
    cloud_source = (ROOT / "esp_idf_demo" / "main" / "cloud_client.c").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")

    assert "DEMO_CLOUD_ERR_RECOVERABLE_TURN" in cloud_header
    assert "recoverable_error_received" in cloud_source
    error_handler = cloud_source.split('strcmp(type, "error") == 0', 1)[1].split(
        "cJSON_Delete(root)", 1
    )[0]
    assert 'cloud_json_get_bool_default(root, "recoverable", false)' in error_handler
    assert error_handler.index("recoverable_error_received") < error_handler.index(
        "error_received = true"
    )
    assert error_handler.index('"error_code"') < error_handler.index("error_received = true")
    finish_body = cloud_source.split("esp_err_t cloud_client_idiom_game_finish_turn", 1)[1].split(
        "void cloud_client_idiom_game_close", 1
    )[0]
    assert "DEMO_CLOUD_ERR_RECOVERABLE_TURN" in finish_body

    game_loop = main.split("static esp_err_t app_run_idiom_game_loop", 1)[1].split(
        "static esp_err_t run_trigger_pipeline", 1
    )[0]
    recoverable_branch = game_loop.split(
        "if (ret == DEMO_CLOUD_ERR_RECOVERABLE_TURN)", 1
    )[1].split("if (ret != ESP_OK)", 1)[0]
    assert "cloud_client_idiom_game_close" not in recoverable_branch
    assert "app_idiom_game_should_prompt_misheard(metrics.error_code)" in recoverable_branch
    assert "if (should_prompt && !rescue_active)" in recoverable_branch
    assert "app_idiom_game_is_clear_human_attempt" in recoverable_branch
    assert "app_idiom_game_play_recovery_feedback" in recoverable_branch
    assert "app_idiom_game_grant_rescue_bonus" in recoverable_branch
    assert "action=attempt_budget_preserved" in recoverable_branch
    assert "ret = ESP_OK" in recoverable_branch
    assert "continue" in recoverable_branch


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


def test_empty_game_turn_uses_limited_feedback_then_rearms_vad() -> None:
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")

    assert "#define APP_IDIOM_GAME_EMPTY_PROMPT_FLOOR_MS 1500" in main
    assert "APP_IDIOM_GAME_MISHEARD_PROMPT_PATH" not in main
    assert 'app_play_idiom_cloud_prompt("misheard")' in main
    assert "app_idiom_game_should_prompt_misheard" in main
    for error_code in ("empty_decoded_audio", "asr_empty_text", "asr_no_final_text"):
        assert f'"{error_code}"' in main

    game_loop = main.split("static esp_err_t app_run_idiom_game_loop", 1)[1].split(
        "static esp_err_t run_trigger_pipeline", 1
    )[0]
    assert "rescue_active" in game_loop
    assert "remaining_attempt_budget_us" in game_loop
    assert "app_idiom_game_play_recovery_feedback" in game_loop
    assert "APP_IDIOM_GAME_RESCUE_BONUS_MS" in main
    assert "app_idiom_game_grant_rescue_bonus" in game_loop


def test_idiom_feedback_policy_recovers_for_clear_speech_without_noise_loop() -> None:
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")

    assert "#define APP_IDIOM_GAME_FULL_FEEDBACK_LIMIT 2" in main
    assert "#define APP_IDIOM_GAME_SHORT_FEEDBACK_LIMIT 1" in main
    assert "#define APP_IDIOM_GAME_FULL_FEEDBACK_INTERVAL_MS 4000" in main
    assert "#define APP_IDIOM_GAME_CLEAR_SPEECH_MIN_MS 400" in main
    clear_attempt = main.split(
        "static bool app_idiom_game_is_clear_human_attempt", 1
    )[1].split("static app_idiom_game_feedback_action_t", 1)[0]
    assert "cloud_metrics->question_text[0] != '\\0'" in clear_attempt
    assert "record_metrics->voice_started" in clear_attempt
    assert "record_metrics->vad_stopped" in clear_attempt
    assert "record_metrics->elapsed_ms >= APP_IDIOM_GAME_CLEAR_SPEECH_MIN_MS" in clear_attempt

    choose_feedback = main.split(
        "static app_idiom_game_feedback_action_t app_idiom_game_choose_feedback", 1
    )[1].split("static esp_err_t app_idiom_game_play_recovery_feedback", 1)[0]
    first_full = choose_feedback.index("feedback->full_count == 0")
    noise_suppression = choose_feedback.index("!clear_human_attempt")
    second_full = choose_feedback.index("APP_IDIOM_GAME_FULL_FEEDBACK_LIMIT")
    short_ack = choose_feedback.index("APP_IDIOM_GAME_SHORT_FEEDBACK_LIMIT")
    assert first_full < noise_suppression < second_full < short_ack
    assert "DEMO_RECORD_RETRY_REARM_PROMPT_PATH" in main


def test_exhausted_active_turn_does_not_play_misheard_immediately_before_exit() -> None:
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")
    game_loop = main.split("static esp_err_t app_run_idiom_game_loop", 1)[1].split(
        "static esp_err_t run_trigger_pipeline", 1
    )[0]
    recoverable_branch = game_loop.split(
        "if (ret == DEMO_CLOUD_ERR_RECOVERABLE_TURN)", 1
    )[1].split("if (ret != ESP_OK)", 1)[0]
    nonmeaningful_branch = game_loop.split("if (outcome_nonmeaningful)", 1)[1].split(
        "if (!outcome_meaningful", 1
    )[0]

    for branch in (recoverable_branch, nonmeaningful_branch):
        grant_index = branch.index("app_idiom_game_grant_rescue_bonus")
        positive_budget_index = branch.index("remaining_attempt_budget_us > 0")
        feedback_index = branch.index("app_idiom_game_play_recovery_feedback")
        assert grant_index < positive_budget_index < feedback_index


def test_game_turn_outcome_controls_attempt_budget() -> None:
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")

    game_loop = main.split("static esp_err_t app_run_idiom_game_loop", 1)[1].split(
        "static esp_err_t run_trigger_pipeline", 1
    )[0]
    for helper in (
        "app_idiom_game_outcome_is_missing",
        "app_idiom_game_outcome_is_meaningful",
        "app_idiom_game_outcome_is_nonmeaningful",
        "app_idiom_game_outcome_is_exit",
    ):
        assert helper in main
        assert helper in game_loop
    assert "realtime_session.turn_outcome" in game_loop
    assert "realtime_session.turn_reason" in game_loop
    assert "rescue_active" in game_loop
    assert "remaining_attempt_budget_us" in game_loop
    assert "action=nonmeaningful_response_deferred" in game_loop
    assert "action=turn_outcome_compat_legacy" in game_loop
    assert "app_idiom_game_grant_rescue_bonus" in game_loop
    assert "const bool play_response = game_ended || !outcome_nonmeaningful" in game_loop
    assert "noise_hard_deadline_us" not in game_loop


def test_game_turn_reason_is_optional_and_parsed_by_the_board() -> None:
    cloud_header = (ROOT / "esp_idf_demo" / "main" / "cloud_client.h").read_text(
        encoding="utf-8"
    )
    cloud_source = (ROOT / "esp_idf_demo" / "main" / "cloud_client.c").read_text(
        encoding="utf-8"
    )

    assert "char turn_reason[24];" in cloud_header
    done_handler = cloud_source.split('strcmp(type, "done") == 0', 1)[1].split(
        'strcmp(type, "idle_exit_ack") == 0', 1
    )[0]
    assert 'cloud_opus_uplink_copy_optional_string(root, "turn_reason"' in done_handler
    assert "uplink->session.turn_reason" in done_handler


def test_attempt_budget_is_checked_before_vad_and_bounds_the_wait_window() -> None:
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")
    game_loop = main.split("static esp_err_t app_run_idiom_game_loop", 1)[1].split(
        "static esp_err_t run_trigger_pipeline", 1
    )[0]
    consume_helper = main.split(
        "static void app_idiom_game_consume_attempt_budget", 1
    )[1].split("static uint32_t app_idiom_game_vad_wait_timeout_ms", 1)[0]

    pre_wait_check = game_loop.index("if (remaining_attempt_budget_us <= 0)")
    wait_timeout_index = game_loop.index("app_idiom_game_vad_wait_timeout_ms")
    wait_index = game_loop.index("audio_in_wait_for_game_speech_start")
    consume_index = game_loop.index("app_idiom_game_consume_attempt_budget")
    turn_start_index = game_loop.index("char turn_id[64]")

    assert pre_wait_check < wait_timeout_index < wait_index
    assert wait_index < consume_index < turn_start_index
    assert "DEMO_WAIT_FOR_SPEECH_TIMEOUT_MS" in main
    assert '"attempt_budget_exhausted"' in game_loop
    assert "*remaining_budget_us -= elapsed_us;" in consume_helper
    assert "elapsed_us >= *remaining_budget_us" not in consume_helper


def test_game_idle_deadline_sends_device_scoped_exit_and_restores_wake_flow() -> None:
    main = (ROOT / "esp_idf_demo" / "main" / "main.c").read_text(encoding="utf-8")
    cloud_header = (ROOT / "esp_idf_demo" / "main" / "cloud_client.h").read_text(
        encoding="utf-8"
    )
    cloud_source = (ROOT / "esp_idf_demo" / "main" / "cloud_client.c").read_text(
        encoding="utf-8"
    )

    assert "#define APP_IDIOM_GAME_BASE_ATTEMPT_MS 15000" in main
    assert "#define APP_IDIOM_GAME_RESCUE_BONUS_MS 10000" in main
    assert "APP_IDIOM_GAME_NORMAL_IDLE_MS" not in main
    assert "APP_IDIOM_GAME_POST_PRESENCE_IDLE_MS" not in main
    assert "APP_IDIOM_GAME_POST_NONMEANINGFUL_IDLE_MS" not in main
    assert "APP_IDIOM_GAME_NOISE_HARD_IDLE_MS" not in main
    assert "#define APP_IDIOM_GAME_HARD_IDLE_MS 180000" not in main
    assert "#define APP_IDIOM_GAME_IDLE_EXIT_ACK_TIMEOUT_MS 2000" in main
    assert "APP_IDIOM_GAME_PROMPT_MAX_BYTES" not in main
    assert "static esp_err_t app_play_idiom_cloud_prompt" in main
    assert "cloud_client_build_idiom_prompt_audio_url" in cloud_header
    assert "cloud_client_build_idiom_prompt_audio_url" in cloud_source
    assert '"api/v5/realtime/idiom-game/prompts/%s/audio"' in cloud_source
    assert "cloud_client_idiom_game_idle_exit" in cloud_header
    assert "cloud_client_idiom_game_idle_exit" in cloud_source
    assert 'cJSON_AddStringToObject(root, "type", "idle_exit")' in cloud_source
    assert 'cJSON_AddStringToObject(root, "event_id", event_id)' in cloud_source
    assert 'cJSON_AddStringToObject(root, "reason", reason)' in cloud_source
    assert "idle_exit_ack_received" in cloud_source
    assert 'strcmp(type, "idle_exit_ack") == 0' in cloud_source

    game_loop = main.split("static esp_err_t app_run_idiom_game_loop", 1)[1].split(
        "static esp_err_t run_trigger_pipeline", 1
    )[0]
    assert 'app_play_idiom_cloud_prompt("idle_exit"' in main
    assert "app_idiom_game_perform_idle_exit" in game_loop
    assert 'app_play_idiom_cloud_prompt("presence"' in game_loop
    assert "rescue_active" in game_loop
    assert "rescue_timeout_reason" in game_loop
    assert "no_meaningful_after_presence_prompt" in game_loop
    assert "no_meaningful_after_misheard_prompt" in game_loop
    assert "attempt_budget_exhausted" in game_loop
    assert "cloud_client_idiom_game_idle_exit" in main
    assert "s_local_idiom_context_until_us = 0" in game_loop
    assert "action=restore_wakenet" in main


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
