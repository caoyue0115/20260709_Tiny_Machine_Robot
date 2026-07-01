# Windows COM6 Firmware Bring-Up

Use PowerShell.

```powershell
cd C:\esp_projects\20260701_Tiny_Machine_Robot_bringup
. C:\esp\v5.5.4\esp-idf\export.ps1
$env:TINY_WIFI_SSID='your-wifi'
$env:TINY_WIFI_PASSWORD='your-password'
$env:TINY_DEVICE_ID='tiny-com6-001'
idf.py -C esp_idf_demo set-target esp32s3
idf.py -C esp_idf_demo `
  -DDEMO_WIFI_SSID="$env:TINY_WIFI_SSID" `
  -DDEMO_WIFI_PASSWORD="$env:TINY_WIFI_PASSWORD" `
  -DDEMO_SERVER_BASE_URL="http://tiny.praystack.top" `
  -DDEMO_DEVICE_ID="$env:TINY_DEVICE_ID" `
  build
idf.py -C esp_idf_demo -p COM6 flash monitor
```

Warning: `-DDEMO_WIFI_PASSWORD=...` is expanded into the ESP-IDF CMake/build tree. Treat `esp_idf_demo\build` as sensitive until it is removed.

After flashing, clear the shell secrets and delete local build artifacts:

```powershell
Remove-Item Env:\TINY_WIFI_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:\TINY_WIFI_SSID -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force esp_idf_demo\build
```

Acceptance requires saying `小明同学`, asking one coffee question, and hearing a coffee answer.
