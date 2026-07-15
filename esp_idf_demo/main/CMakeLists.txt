idf_component_register(SRCS "main.c" "trigger_input.c" "audio_in.c" "cloud_client.c" "audio_out.c" "board_audio.c" "app_network.cc" "wake_word_service.c" "local_command_service.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_http_client json driver esp_timer esp_event esp_netif esp_wifi nvs_flash
                                esp_vocat espressif__esp_lcd_touch esp_websocket_client spiffs
                                esp_app_format app_update 78__esp-wifi-connect espressif__esp-sr)

set(DEMO_LOCAL_STRING_DEFINITIONS
    DEMO_WIFI_SSID
    DEMO_WIFI_PASSWORD
    DEMO_SERVER_BASE_URL
    DEMO_DEVICE_ID
)

foreach(name IN LISTS DEMO_LOCAL_STRING_DEFINITIONS)
    if(DEFINED ${name})
        target_compile_definitions(${COMPONENT_LIB} PRIVATE ${name}="${${name}}")
    endif()
endforeach()

# Active MultiNet inference and Opus/WebSocket upload share the audio pipeline
# task. Keep the stack default outside config.h so local credentials and device
# settings remain untracked, while still allowing an idf.py -D override.
if(NOT DEFINED DEMO_PIPELINE_TASK_STACK_SIZE)
    set(DEMO_PIPELINE_TASK_STACK_SIZE 40960)
endif()
target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE DEMO_PIPELINE_TASK_STACK_SIZE=${DEMO_PIPELINE_TASK_STACK_SIZE}
)

file(MAKE_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../spiffs")
spiffs_create_partition_image(storage ../spiffs FLASH_IN_PROJECT)
