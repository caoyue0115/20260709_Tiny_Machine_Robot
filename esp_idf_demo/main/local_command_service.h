#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifndef DEMO_LOCAL_COMMAND_TEXT_MAX_LEN
#define DEMO_LOCAL_COMMAND_TEXT_MAX_LEN 64
#endif

typedef enum {
    LOCAL_COMMAND_KIND_NONE = 0,
    LOCAL_COMMAND_KIND_IDIOM_START,
    LOCAL_COMMAND_KIND_IDIOM_MODE,
    LOCAL_COMMAND_KIND_IDIOM_REPEAT,
} local_command_kind_t;

typedef struct {
    bool detected;
    bool accepted;
    bool timed_out;
    int command_id;
    float probability;
    char text[DEMO_LOCAL_COMMAND_TEXT_MAX_LEN];
    char raw_string[256];
} local_command_result_t;

esp_err_t local_command_service_init(void);
esp_err_t local_command_service_begin_session(void);
esp_err_t local_command_service_feed(const uint8_t *pcm,
                                     size_t pcm_bytes,
                                     local_command_result_t *out_result);
esp_err_t local_command_service_detect_buffer(const uint8_t *pcm,
                                              size_t pcm_bytes,
                                              local_command_result_t *out_result);
void local_command_service_end_session(void);
void local_command_service_deinit(void);
bool local_command_service_is_available(void);
const char *local_command_service_text_for_id(int command_id);
local_command_kind_t local_command_service_kind_for_id(int command_id);
