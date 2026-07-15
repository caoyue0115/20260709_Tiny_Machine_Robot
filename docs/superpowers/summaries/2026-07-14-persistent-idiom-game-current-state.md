# 成语接龙持续会话现状报告（2026-07-14）

## 1. 文档范围与版本状态

- 工作区：`D:\20260709_Tiny_Machine_Robot-merge`
- 当前分支：`merge`
- 本报告描述的是本地修改后的源代码行为。
- 本轮没有提交、推送、云端重启或板端烧录。
- 云端当前已部署的基础版本仍是 `6b7a0c8`；本轮云端 Python 代码没有变化。
- 板端必须重新 build/flash 后，才会实际获得本报告中的 VAD 和可恢复错误行为。
- `esp_idf_demo/main/config.h` 与 `esp_idf_demo/sdkconfig.multinet_eval` 属于受保护的本地配置，不在本轮修改或建议提交范围内。报告不记录其中的 Wi-Fi、局域网地址和设备 ID。

## 2. 当前整体架构

普通咖啡问答继续使用原来的唤醒加单轮链路；只有进入成语接龙后才切换到独立持续 WebSocket：

```text
普通状态
WakeNet“小明同学”
→ 单轮录音/ASR
→ 云端识别为开始成语接龙
→ 播放开局静态音频
→ 建立成语游戏 WebSocket

游戏状态
WebSocket 保持连接
→ 本地麦克风采样、能量 VAD 和 200ms pre-roll
→ 没有用户语音时不上传、不创建云端 ASR
→ 发现语音后按 turn_id 创建单轮 ASR并上传 Opus
→ 收到 done 后播放静态回复
→ 不再次唤醒，重新进入本地 VAD
→ 退出或游戏结束后关闭游戏 WebSocket并恢复 WakeNet
```

游戏 WebSocket 地址为：

```text
/api/v5/realtime/idiom-game/opus-stream
```

连接按 `device_id` 绑定；游戏状态也按 `device_id` 保存。云端状态为单进程内存状态，服务重启或多 worker 共享不在当前保证范围内。

## 3. 板端状态机

游戏内部状态编号如下：

| 编号 | 状态 | 含义 |
|---:|---|---|
| 0 | `APP_IDIOM_GAME_SOCKET_IDLE` | WebSocket 空闲，无 active turn |
| 1 | `APP_IDIOM_GAME_PLAYBACK` | 播放云端返回的静态音频 |
| 2 | `APP_IDIOM_GAME_ECHO_GUARD` | 播放结束后的回声保护 |
| 3 | `APP_IDIOM_GAME_VAD_ARMED` | 开始进入麦克风/VAD监听流程 |
| 4 | `APP_IDIOM_GAME_UPLOADING` | 已确认用户开口，采集并上传本轮音频 |
| 5 | `APP_IDIOM_GAME_WAITING_REPLY` | 已发送 `utterance_end`，等待结果 |

注意：`idiom_game_state=3` 在调用麦克风监听函数前打印，因此它表示“准备进入 VAD 流程”，不是最精确的实际 armed 时刻。实际 armed 以后应以新增日志为准：

```text
stage=idiom_game_waiting_speech event=armed elapsed_ms=...
```

## 4. 播放结束到 VAD armed 的精确时间

当前时间顺序如下：

1. 回复音频完全播放结束。
2. 板端等待固定 `200ms` 回声保护，期间不打开上传、不创建 ASR。
3. 打开并配置麦克风。
4. 麦克风打开完成后开始计算监听函数时间，先等待名义 `150ms` 稳定期。
5. 稳定期内仍把真实 PCM 写入 pre-roll 环形缓冲区，但不执行语音触发判断。
6. 音频块大小为 `2048 bytes`，在 `16kHz / 单声道 / 16-bit` 下每块约 `64ms`。
7. 第一个跨过 `150ms` 边界的块只用于宣布 armed，仍不用于触发，避免把麦克风/I2S启动瞬态算成语音。

因此：

- 配置上的 armed 稳定期是 `150ms`。
- 受 `64ms` 块边界影响，`event=armed` 通常约在麦克风监听计时的 `192ms` 左右出现。
- 从回复播放结束算起，实际 armed 通常约为：

```text
200ms 回声保护 + 麦克风配置耗时 + 约 192ms
```

- 即约 `392ms + 麦克风配置耗时`，实际数值应以串口 `event=armed elapsed_ms` 和麦克风初始化日志为准。

## 5. VAD 如何触发

### 5.1 起始触发条件

每个 `64ms` PCM 块计算 16-bit 样本绝对值平均值：

```text
chunk_level = average(abs(pcm16_sample))
```

当前起始阈值：

```text
DEMO_WAITING_SPEECH_START_THRESHOLD = 900
```

触发不是单块判定，而是要求：

```text
连续两个 64ms 块的 chunk_level >= 900
```

即名义连续语音保持时间：

```text
DEMO_SPEECH_START_HOLD_MS = 128ms
```

任意一个块低于 `900` 都会把累计保持时间清零，必须重新连续满足两块。

按当前块粒度，麦克风监听计时开始后，最早通常约在 `320ms` 才可能触发：

```text
约 192ms：宣布 armed并丢弃边界块
约 256ms：第一个有效高能量块
约 320ms：第二个有效高能量块，触发 speech_detected
```

从回复播放结束算，理论最早触发约为：

```text
200ms 回声保护 + 麦克风配置耗时 + 约 320ms
```

也就是至少约 `520ms + 麦克风配置耗时`。真实调度和 I2S 读取会有少量偏差。

### 5.2 pre-roll

- 环形 pre-roll 目标：`200ms`。
- PCM 大小：`16000 × 0.2 × 1 × 2 = 6400 bytes`。
- 稳定期、armed 等待期和连续触发确认期的真实 PCM 都先写入环形缓冲。
- 触发时按正确时间顺序快照最近 `200ms`，不是零填充。
- 因此等待 `128ms` 连续确认不会裁掉用户首字，真实开头仍在 pre-roll 中。

### 5.3 结束触发条件

用户开口后，后续块使用低能量阈值：

```text
DEMO_RECORD_VAD_SILENCE_THRESHOLD = 300
```

连续低能量目标为 `200ms`。由于块长是 `64ms`，累计字节达到目标需要 4 个块，因此实际通常约为 `256ms` 尾静音，然后发送 `utterance_end`。

单轮最大 PCM 容量按 `4s` 限制，包含 pre-roll。到达最大长度也会正常结束本轮，让 ASR 做最终识别。

## 6. 用户一直不说话时的行为

一次本地等待窗口为：

```text
DEMO_WAIT_FOR_SPEECH_TIMEOUT_MS = 3000ms
```

如果约 3 秒内没有连续 `128ms` 达到阈值：

```text
event=timeout action=silent_rearm
→ 不发送 utterance_start
→ 不上传 PCM/Opus
→ 云端不创建 ASR
→ 不播放“请重试”
→ 不推进成语状态
→ WebSocket继续保持连接
→ 板端进入下一次监听
```

当前实现会在每个 3 秒窗口结束时关闭并重新打开麦克风，并重新经过游戏循环的 `200ms` guard 和麦克风稳定期。因此它是“静默分段重新监听”，不是麦克风句柄永久不关闭。重新打开期间存在短暂不可触发窗口，这是当前实现的已知行为。

## 7. 本轮修复后的可恢复错误处理

云端 persistent endpoint 对 active turn 的解码、协议或 ASR错误返回：

```json
{
  "type": "error",
  "turn_id": "当前轮ID",
  "error_code": "...",
  "recoverable": true
}
```

修复前，板端忽略 `recoverable`，把任何单轮错误当成连接故障：关闭 WebSocket、重连并播放本地“请重试”。

修复后：

```text
recoverable=true
→ 只结束当前轮
→ 保留同一个 WebSocket
→ 不清除 device_id 游戏状态
→ 不播放“请重试”
→ 静默重新进入 VAD
```

`recoverable` 和 `error_code` 会先完整写入，再发布 `error_received` 标志，避免等待任务看到半写入的错误状态。

真实网络断开、WebSocket事件错误、60秒结果等待超时、发送失败等非 recoverable 错误仍按真实故障处理：关闭旧连接、最多尝试 3 次连接，退避约为 `500ms / 1000ms / 1500ms`。连接恢复后才播放本地错误提示；连接无法恢复则结束游戏管线并恢复外层系统。

本次问题的云端证据是：

```text
error_code=asr_empty_text
DashScope realtime ASR returned empty text
```

这类结果现在会静默重新监听，不再形成“空文本 → 重连 → 请重试 → 回声再触发”的循环。

## 8. WebSocket、turn_id 与 ASR生命周期

### 8.1 连接级生命周期

- 建立游戏 WebSocket时只绑定 `device_id`，不创建 ASR。
- WebSocket客户端关闭自动重连，由游戏状态机执行有界重连。
- ESP WebSocket managed component 默认每 `10s` 发送 PING，等待 PONG 的默认超时为 `120s`。
- 游戏本地 TTL 默认 `900s`。

### 8.2 单轮协议

每轮 `turn_id` 格式：

```text
{device_id}-{esp_timer_us}-{turn_sequence}
```

消息顺序：

```text
板端：utterance_start(turn_id)
板端：framed Opus binary
板端：utterance_end(turn_id)
云端：asr_final(turn_id)
云端：done(turn_id)
```

音频参数：

- PCM：`16kHz / mono / 16-bit`。
- Opus 帧长：`60ms`。
- Opus 目标码率：`24000 bit/s`。
- 板端等待 `done/error` 上限：`60000ms`。

云端只在 `utterance_start` 后创建该轮 ASR和 Opus decoder；`utterance_end` 后停止接收音频，通知 ASR结束输入，等待最终结果，然后销毁单轮资源。连接回到 idle 时没有 ASR实例，也没有上传音频。

板端只接受与当前 `turn_id` 相同的 `asr_final/error/done`；迟到或错误轮次消息被丢弃。成功 `done` 必须携带：

```text
skill_name
skill_active
end_skill_state
audio_stream_url
turn_id
```

## 9. MultiNet 分层

WakeNet仍只负责“小明同学”。当前 MultiNet 命令如下：

| ID | 规范文本 | 使用范围 |
|---:|---|---|
| 100–102 | 开始成语接龙 | 普通唤醒后的输入可拦截 |
| 110–111 | 简单模式 | 仅成语上下文有效 |
| 120–121 | 困难模式 | 仅成语上下文有效 |
| 140 | 我没听清 | 仅成语上下文有效 |
| 141 | 我没听到 | 仅成语上下文有效 |
| 142 | 再说一遍 | 仅成语上下文有效 |
| 143 | 重复一遍 | 仅成语上下文有效 |
| 144 | 刚才是什么 | 仅成语上下文有效 |

退出命令 `130/131` 已删除。退出、自由成语和其他开放表达允许进入 DashScope ASR。

MultiNet模型为 `mn7_cn`，命令会话配置上限 `3000ms`，接受概率阈值 `0.70`。命中时提交规范化文本，不创建云端 ASR；未命中、超时或不可用时，把已经缓存的真实 PCM 继续送入同一云端回合，不丢失开头。

## 10. 云端成语判定顺序

游戏状态有效时：

```text
确定性控制意图
→ 本地成语词库
→ 一次结构化 LLM 兜底
→ 静态音频计划
```

确定性控制优先处理退出、重复和难度切换。当前常见退出表达包括“退出、不玩了、结束游戏、结束接龙、先这样、停止、结束吧”等；重复表达包括“没听清、没听到、再说一次、重复一下、刚才是什么”等。

本地词库包含 `29493` 条成语。只有文本不属于确定性控制且未命中本地词库时，才可能调用一次 LLM。空白和纯语气噪声不会调用 LLM。

LLM返回：

```json
{
  "intent": "idiom | exit | repeat | easy | hard | invalid | off_topic",
  "normalized_idiom": "",
  "first_py": "",
  "last_py": "",
  "is_idiom": false,
  "matches_expected_pinyin": false,
  "confidence": 0.0
}
```

未知成语只有同时满足以下条件才被接受：

- `intent == idiom`
- `is_idiom == true`
- `normalized_idiom` 是四个汉字
- `confidence >= 0.8`
- `normalize_pinyin(first_py) == expected_py`
- `normalize_pinyin(last_py)` 非空且格式有效

`matches_expected_pinyin` 只记录日志，不参与服务器最终接受判断。拼音统一去声调、转小写，并把 `ü` 归一为 `v`。

## 11. 游戏状态、难度与胜负

每个 `device_id` 的云端状态包含：

```text
expected_py
used_words
valid_user_turns
robot_difficulty
last_robot_word
updated_at
```

默认云端难度为普通模式：

| 模式 | 机器人候选池上限 | 连续成功目标 |
|---|---:|---:|
| 简单 | 500 | 8轮 |
| 普通 | 3000 | 15轮 |
| 困难 | 10000 | 25轮 |
| 大师/全量 | 全部可播放成语 | 50轮 |

切换难度保留 `expected_py`、已使用成语和 `last_robot_word`，但把连续成功轮数重新置零。

下列情况结束游戏并清除云端状态：

- 确定性或 LLM判定退出。
- 用户达到当前难度的连续成功目标。
- 用户接对后机器人找不到可播放且未使用的接龙候选。

云端状态 TTL 为最后一次保存后的 `900s`。板端本地游戏上下文也是 `900s`，但当前只在进入游戏或 MultiNet模式/重复命令成功时刷新；普通 ASR成语成功轮不会刷新板端本地 TTL。这是当前实现需要留意的边界。

## 12. 回复文本和静态音频

正常游戏不使用运行时动态 TTS。

| 场景 | 静态音频计划 |
|---|---|
| 开始 | `idiom_game/start + idiom_game/robot_first + idioms/{成语}` |
| 正常机器人接龙 | `idioms/{成语}` |
| 重复上一句 | `idioms/{last_robot_word}` |
| 简单/普通/困难/大师 | 对应 `idiom_game/mode_*` |
| 退出 | `idiom_game/exit` |
| 未找到成语 | `idiom_game/not_found` |
| 无关内容 | `idiom_game/continue_prompt` |
| LLM失败或低置信度 | `idiom_game/retry` |
| 固定素材不可用 | `idiom_game/static_error` |

开局文本保留“好呀，我们玩成语接龙。小机仔先来：{成语}。”；正常后续和重复只播放四字成语，不再引用 `turn_prompt` 或 `pinyin/*`。

启动时校验固定素材和成语素材。WAV会检查 `16kHz / mono / 16-bit / PCM / 非空可读`；raw PCM没有文件头可验证采样率和声道，只能检查文件可读、非空并且字节数符合 16-bit 对齐，采样格式依赖素材生成契约。

不可用的成语会从开局池和机器人候选池排除。最后一次云端部署校验记录为 `29493 playable / 0 invalid`。如果 `static_error` 本身不可用，服务启动失败；其他固定素材不可用时运行时映射为 `static_error`。

## 13. 如何从串口判断行为

### 13.1 正常静默重新监听

```text
idiom_game_state=3
stage=idiom_game_waiting_speech event=armed elapsed_ms=...
stage=idiom_game_waiting_speech event=timeout elapsed_ms=... max_level=... action=silent_rearm
idiom_game_state=0
idiom_game_state=2
idiom_game_state=3
```

期间不得出现：

```text
utterance_start
utterance_end
retry_prompt
```

### 13.2 真实语音触发

```text
stage=idiom_game_waiting_speech event=armed ...
stage=idiom_game_waiting_speech event=speech_detected ... hold_ms=128 speech_prefix_bytes=6400
idiom_game_state=4
idiom_game_ws utterance_start turn_id=...
idiom_game_state=5
idiom_game_ws utterance_end turn_id=...
```

### 13.3 ASR空文本等可恢复错误

```text
idiom_game_ws turn_error turn_id=... error_code=asr_empty_text recoverable=1 action=keep_socket
idiom_game_turn_recoverable turn_id=... error_code=asr_empty_text action=silent_rearm
```

随后应直接回到监听；不得出现新的 `ws_connect_start` 和 `retry_prompt`。

### 13.4 真实连接故障

非 recoverable 故障仍会看到：

```text
idiom_game_turn_failed / idiom_game_turn_upload_failed
ws_connect_start
idiom_game_ws connected 或 reconnect_failed
retry_prompt（连接恢复后）
```

## 14. 验证结果

本轮验证结果：

- 新增 VAD 和 recoverable error 测试先失败，完成实现后通过。
- `tests/test_esp_assets.py`：`37 passed`。
- `tests/test_tiny_esp_guards.py` 排除既有 provider 断言：`12 passed, 1 deselected`。
- `tests/test_opus_uplink.py`：`34 passed, 19 skipped`。
- voice-skills、realtime、静态音频相关集合：`124 passed, 49 subtests passed`。
- 全量测试：`287 passed, 19 skipped, 49 subtests passed, 1 known failure`。
- 唯一失败是业务修改前遗留的 Volcengine默认值断言；当前预期 provider 是 DashScope，按既有决定不修改该测试、不计为本次回归。
- ESP-IDF `v5.5.4` 完整 build 成功。
- 生成的应用镜像大小：`0x1c3400 bytes`。
- 最小 app 分区剩余：`0x13cc00 bytes`，约 `41%`。
- 编译只有既有未使用 OTA符号警告，没有本次 VAD/WebSocket修改产生的编译错误。

## 15. 本轮代码改动与尚未完成的验收

本轮新增/修改：

- `esp_idf_demo/main/audio_in.c`
- `esp_idf_demo/main/cloud_client.c`
- `esp_idf_demo/main/cloud_client.h`
- `esp_idf_demo/main/main.c`
- `tests/test_tiny_esp_guards.py`
- 本报告文件

工作区还包含上一轮尚未提交但已编译通过的 pipeline stack修复：

- `esp_idf_demo/main/CMakeLists.txt`
- `tests/test_esp_assets.py`

自动验证已经完成，但仍需硬件实测：

1. 烧录本地新固件。
2. 进入游戏后保持安静至少 10–15 秒，确认只出现多次 `event=timeout action=silent_rearm`，没有重试音频。
3. 在 armed 后说一个成语，确认出现 `hold_ms=128`、`speech_prefix_bytes=6400` 并正常识别。
4. 制造一次很短的杂音，确认若云端返回 `asr_empty_text`，同一 WebSocket保持连接且没有“请重试”。
5. 连续完成至少两轮并正常退出，确认 `end_skill_state=1` 后恢复 WakeNet。
6. 再执行一次普通咖啡问答，确认单轮链路未变化。

在上述硬件验收完成前，当前建议是“暂不提交”。硬件通过后可提交源代码、测试和本报告，但必须排除 `config.h` 与 `sdkconfig.multinet_eval`。
