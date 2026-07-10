#include "local_command_service.h"

#include "config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_mn_iface.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#include "model_path.h"

static const char *TAG = "local_command";

typedef struct {
    int command_id;
    const char *pinyin;
    const char *text;
    local_command_kind_t kind;
} local_command_entry_t;

static const local_command_entry_t s_command_entries[] = {
    {100, "jin ru cheng yu jie long", "开始成语接龙", LOCAL_COMMAND_KIND_IDIOM_START},
    {101, "kai shi cheng yu jie long", "开始成语接龙", LOCAL_COMMAND_KIND_IDIOM_START},
    {102, "wan cheng yu jie long", "开始成语接龙", LOCAL_COMMAND_KIND_IDIOM_START},
    {110, "jian dan mo shi", "简单模式", LOCAL_COMMAND_KIND_IDIOM_MODE},
    {111, "jian dan yi dian", "简单模式", LOCAL_COMMAND_KIND_IDIOM_MODE},
    {120, "kun nan mo shi", "困难模式", LOCAL_COMMAND_KIND_IDIOM_MODE},
    {121, "nan yi dian", "困难模式", LOCAL_COMMAND_KIND_IDIOM_MODE},
    {130, "tui chu you xi", "退出游戏", LOCAL_COMMAND_KIND_IDIOM_EXIT},
    {131, "bu wan le", "退出游戏", LOCAL_COMMAND_KIND_IDIOM_EXIT},
};

typedef struct {
    bool initialized;
    bool unavailable;
    bool commands_allocated;
    bool session_active;
    bool result_ready;
    srmodel_list_t *models;
    const esp_mn_iface_t *multinet;
    model_iface_data_t *model_data;
    int sample_rate;
    int chunk_samples;
    int16_t *chunk;
    size_t chunk_fill_samples;
    local_command_result_t last_result;
} local_command_state_t;

static local_command_state_t s_local = {0};

static const local_command_entry_t *local_command_entry_for_id(int command_id)
{
    for (size_t i = 0; i < sizeof(s_command_entries) / sizeof(s_command_entries[0]); ++i) {
        if (s_command_entries[i].command_id == command_id) {
            return &s_command_entries[i];
        }
    }
    return NULL;
}

static void local_command_result_clear(local_command_result_t *result)
{
    if (result != NULL) {
        memset(result, 0, sizeof(*result));
    }
}

static void local_command_copy_result(local_command_result_t *dst, const local_command_result_t *src)
{
    if (dst != NULL && src != NULL) {
        *dst = *src;
    }
}

static void local_command_log_result(const local_command_result_t *result)
{
    if (result == NULL || !result->detected) {
        return;
    }
    ESP_LOGI(TAG, "local_multinet_result detected=1 command_id=%d text=%s prob=%.2f shadow=%d intercept=%d",
             result->command_id,
             result->text[0] != '\0' ? result->text : "(unknown)",
             (double)result->probability,
             DEMO_LOCAL_COMMAND_SHADOW_MODE,
             DEMO_LOCAL_COMMAND_INTERCEPT_ENABLED);
}

static void local_command_release_resources(void)
{
    if (s_local.commands_allocated) {
        (void)esp_mn_commands_free();
    }
    if (s_local.model_data != NULL && s_local.multinet != NULL && s_local.multinet->destroy != NULL) {
        s_local.multinet->destroy(s_local.model_data);
    }
    if (s_local.models != NULL) {
        esp_srmodel_deinit_with_refcount(s_local.models);
    }
    free(s_local.chunk);
    memset(&s_local, 0, sizeof(s_local));
}

static bool local_command_fill_result(const esp_mn_results_t *mn_results, local_command_result_t *out_result)
{
    if (mn_results == NULL || mn_results->num <= 0 || out_result == NULL) {
        return false;
    }

    int best_index = 0;
    for (int i = 1; i < mn_results->num && i < ESP_MN_RESULT_MAX_NUM; ++i) {
        if (mn_results->prob[i] > mn_results->prob[best_index]) {
            best_index = i;
        }
    }

    const int command_id = mn_results->command_id[best_index];
    const float probability = mn_results->prob[best_index];
    const local_command_entry_t *entry = local_command_entry_for_id(command_id);

    local_command_result_clear(out_result);
    out_result->detected = true;
    out_result->accepted = entry != NULL && probability >= DEMO_LOCAL_COMMAND_MIN_PROB;
    out_result->command_id = command_id;
    out_result->probability = probability;
    snprintf(out_result->text,
             sizeof(out_result->text),
             "%s",
             entry != NULL ? entry->text : "(unknown)");
    snprintf(out_result->raw_string,
             sizeof(out_result->raw_string),
             "%s",
             mn_results->raw_string[0] != '\0' ? mn_results->raw_string : mn_results->string);
    return true;
}

static esp_err_t local_command_detect_current_chunk(local_command_result_t *out_result)
{
    if (s_local.multinet == NULL || s_local.model_data == NULL || s_local.chunk == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    esp_mn_state_t state = s_local.multinet->detect(s_local.model_data, s_local.chunk);
    if (state != ESP_MN_STATE_DETECTED) {
        return ESP_OK;
    }

    esp_mn_results_t *mn_results = s_local.multinet->get_results(s_local.model_data);
    local_command_result_t result = {0};
    if (!local_command_fill_result(mn_results, &result)) {
        return ESP_OK;
    }
    local_command_log_result(&result);
    if (!result.accepted) {
        ESP_LOGI(TAG,
                 "local_multinet_rejected command_id=%d prob=%.2f min_prob=%.2f",
                 result.command_id,
                 (double)result.probability,
                 (double)DEMO_LOCAL_COMMAND_MIN_PROB);
        return ESP_OK;
    }

    s_local.last_result = result;
    s_local.result_ready = true;
    local_command_copy_result(out_result, &result);
    return ESP_OK;
}

esp_err_t local_command_service_init(void)
{
#if !DEMO_LOCAL_COMMAND_ENABLED
    return ESP_ERR_NOT_SUPPORTED;
#else
    if (s_local.initialized) {
        return ESP_OK;
    }
    if (s_local.unavailable) {
        return ESP_ERR_NOT_SUPPORTED;
    }

    s_local.models = esp_srmodel_init("model");
    if (s_local.models == NULL || s_local.models->num <= 0) {
        ESP_LOGW(TAG, "local_multinet_model_partition_missing label=model");
        s_local.unavailable = true;
        return ESP_ERR_NOT_FOUND;
    }

    char *model_name = esp_srmodel_filter(s_local.models, ESP_MN_PREFIX, ESP_MN_CHINESE);
    if (model_name == NULL) {
        model_name = (char *)DEMO_LOCAL_COMMAND_MODEL_NAME;
    }
    if (esp_srmodel_exists(s_local.models, model_name) < 0) {
        ESP_LOGW(TAG, "local_multinet_model_not_found model=%s", model_name);
        local_command_service_deinit();
        s_local.unavailable = true;
        return ESP_ERR_NOT_FOUND;
    }

    s_local.multinet = esp_mn_handle_from_name(model_name);
    if (s_local.multinet == NULL) {
        ESP_LOGW(TAG, "local_multinet_handle_not_found model=%s", model_name);
        local_command_service_deinit();
        s_local.unavailable = true;
        return ESP_ERR_NOT_FOUND;
    }

    s_local.model_data = s_local.multinet->create(model_name, DEMO_LOCAL_COMMAND_DURATION_MS);
    if (s_local.model_data == NULL) {
        ESP_LOGW(TAG, "local_multinet_create_failed model=%s", model_name);
        local_command_service_deinit();
        s_local.unavailable = true;
        return ESP_FAIL;
    }
    if (s_local.multinet->switch_loader_mode != NULL) {
        model_iface_data_t *switched =
            s_local.multinet->switch_loader_mode(s_local.model_data, ESP_MN_LOAD_FROM_PSRAM_FLASH);
        if (switched != NULL) {
            s_local.model_data = switched;
        }
    }
    if (s_local.multinet->set_det_threshold != NULL) {
        (void)s_local.multinet->set_det_threshold(s_local.model_data, DEMO_LOCAL_COMMAND_MIN_PROB);
    }

    s_local.sample_rate = s_local.multinet->get_samp_rate(s_local.model_data);
    s_local.chunk_samples = s_local.multinet->get_samp_chunksize(s_local.model_data);
    if (s_local.sample_rate != DEMO_AUDIO_SAMPLE_RATE || s_local.chunk_samples <= 0) {
        ESP_LOGW(TAG,
                 "local_multinet_audio_format_mismatch model=%s mn_rate=%d app_rate=%d chunk_samples=%d",
                 model_name,
                 s_local.sample_rate,
                 DEMO_AUDIO_SAMPLE_RATE,
                 s_local.chunk_samples);
        local_command_service_deinit();
        s_local.unavailable = true;
        return ESP_ERR_INVALID_STATE;
    }

    s_local.chunk = heap_caps_calloc((size_t)s_local.chunk_samples, sizeof(int16_t), MALLOC_CAP_8BIT);
    if (s_local.chunk == NULL) {
        local_command_service_deinit();
        s_local.unavailable = true;
        return ESP_ERR_NO_MEM;
    }

    esp_err_t ret = esp_mn_commands_alloc(s_local.multinet, s_local.model_data);
    if (ret == ESP_ERR_INVALID_STATE) {
        (void)esp_mn_commands_free();
        ret = esp_mn_commands_alloc(s_local.multinet, s_local.model_data);
    }
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "local_multinet_commands_alloc_failed err=%s", esp_err_to_name(ret));
        local_command_service_deinit();
        s_local.unavailable = true;
        return ret;
    }
    s_local.commands_allocated = true;
    (void)esp_mn_commands_clear();

    for (size_t i = 0; i < sizeof(s_command_entries) / sizeof(s_command_entries[0]); ++i) {
        ret = esp_mn_commands_add(s_command_entries[i].command_id, s_command_entries[i].pinyin);
        if (ret != ESP_OK) {
            ESP_LOGW(TAG,
                     "local_multinet_command_add_failed command_id=%d pinyin=%s err=%s",
                     s_command_entries[i].command_id,
                     s_command_entries[i].pinyin,
                     esp_err_to_name(ret));
            local_command_service_deinit();
            s_local.unavailable = true;
            return ret;
        }
    }

    esp_mn_error_t *errors = esp_mn_commands_update();
    if (errors != NULL) {
        ESP_LOGW(TAG, "local_multinet_commands_update_failed error_count=%d", errors->num);
        local_command_service_deinit();
        s_local.unavailable = true;
        return ESP_ERR_INVALID_STATE;
    }
    ESP_LOGI(TAG,
             "local_multinet_commands_updated count=%u",
             (unsigned)(sizeof(s_command_entries) / sizeof(s_command_entries[0])));
    esp_mn_commands_print();
    esp_mn_active_commands_print();

    s_local.initialized = true;
    ESP_LOGI(TAG,
             "local_multinet_initialized model=%s sample_rate=%d chunk_samples=%d min_prob=%.2f loader=%d",
             model_name,
             s_local.sample_rate,
             s_local.chunk_samples,
             (double)DEMO_LOCAL_COMMAND_MIN_PROB,
             ESP_MN_LOAD_FROM_PSRAM_FLASH);
    return ESP_OK;
#endif
}

esp_err_t local_command_service_begin_session(void)
{
#if !DEMO_LOCAL_COMMAND_ENABLED
    return ESP_ERR_NOT_SUPPORTED;
#else
    esp_err_t ret = local_command_service_init();
    if (ret != ESP_OK) {
        return ret;
    }
    if (s_local.multinet->clean != NULL) {
        s_local.multinet->clean(s_local.model_data);
    }
    s_local.session_active = true;
    s_local.result_ready = false;
    s_local.chunk_fill_samples = 0;
    local_command_result_clear(&s_local.last_result);
    return ESP_OK;
#endif
}

esp_err_t local_command_service_feed(const uint8_t *pcm,
                                     size_t pcm_bytes,
                                     local_command_result_t *out_result)
{
#if !DEMO_LOCAL_COMMAND_ENABLED
    return ESP_ERR_NOT_SUPPORTED;
#else
    local_command_result_clear(out_result);
    if (pcm == NULL || pcm_bytes == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!s_local.initialized || !s_local.session_active) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_local.result_ready) {
        local_command_copy_result(out_result, &s_local.last_result);
        return ESP_OK;
    }

    const size_t sample_count = pcm_bytes / sizeof(int16_t);
    for (size_t i = 0; i < sample_count; ++i) {
        int16_t sample = 0;
        memcpy(&sample, pcm + (i * sizeof(int16_t)), sizeof(sample));
        s_local.chunk[s_local.chunk_fill_samples++] = sample;
        if (s_local.chunk_fill_samples >= (size_t)s_local.chunk_samples) {
            s_local.chunk_fill_samples = 0;
            esp_err_t ret = local_command_detect_current_chunk(out_result);
            if (ret != ESP_OK || s_local.result_ready) {
                return ret;
            }
        }
    }
    return ESP_OK;
#endif
}

esp_err_t local_command_service_detect_buffer(const uint8_t *pcm,
                                              size_t pcm_bytes,
                                              local_command_result_t *out_result)
{
    esp_err_t ret = local_command_service_begin_session();
    if (ret != ESP_OK) {
        return ret;
    }
    ret = local_command_service_feed(pcm, pcm_bytes, out_result);
    local_command_service_end_session();
    return ret;
}

void local_command_service_end_session(void)
{
    s_local.session_active = false;
    s_local.chunk_fill_samples = 0;
}

void local_command_service_deinit(void)
{
    local_command_release_resources();
}

bool local_command_service_is_available(void)
{
    return s_local.initialized && !s_local.unavailable;
}

const char *local_command_service_text_for_id(int command_id)
{
    const local_command_entry_t *entry = local_command_entry_for_id(command_id);
    return entry != NULL ? entry->text : "";
}

local_command_kind_t local_command_service_kind_for_id(int command_id)
{
    const local_command_entry_t *entry = local_command_entry_for_id(command_id);
    return entry != NULL ? entry->kind : LOCAL_COMMAND_KIND_NONE;
}
