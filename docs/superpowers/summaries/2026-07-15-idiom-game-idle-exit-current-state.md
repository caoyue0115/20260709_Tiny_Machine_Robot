# 成语接龙“你还在吗”与空闲退出现状报告（2026-07-15）

> 2026-07-16 更新：本文记录的是上一版 60/30/180 秒策略，现已由
> `docs/superpowers/summaries/2026-07-16-idiom-game-noise-circuit-breaker-current-state.md`
> 取代。当前实现以新报告中的 25/20/30/60 秒策略和 `turn_outcome` 噪声熔断为准。

## 1. 版本状态

- 工作区：`D:\20260709_Tiny_Machine_Robot-merge`
- 分支：`merge`
- 云端线上仍是基础提交 `6b7a0c8`；本报告中的 `idle_exit` 尚未部署到 `18111`。
- 本地 ESP-IDF 5.5.4 build 已通过；新固件尚未烧录。
- `esp_idf_demo/main/config.h` 和 `esp_idf_demo/sdkconfig.multinet_eval` 继续受保护，不属于提交范围。
- 本报告是 2026-07-14 总报告的行为增量；旧报告中“空 ASR 一律静默”的描述已由本报告取代。

## 2. 三种资源状态

```text
游戏 WebSocket
    游戏期间保持连接；idle 时只有心跳

板端 VAD
    只在板端读取少量麦克风 PCM并维护 200ms pre-roll
    不产生网络上传或云端 ASR成本

active turn / 云端 ASR
    只有确认 VAD 后才发送 utterance_start并创建
    utterance_end后等待 asr_final/error并销毁
```

“你还在吗”播放完成后关闭的是 active turn和 ASR，不关闭游戏 WebSocket。VAD在提示播放期间禁止触发，提示结束后经过 200ms 回声保护再次 armed。

## 3. VAD 与单轮录音参数

| 参数 | 当前值 | 实际含义 |
|---|---:|---|
| 播放后回声保护 | 200ms | 禁止机器人回声触发上传 |
| 麦克风稳定期 | 150ms | 受 64ms块边界影响，armed日志通常约 192ms |
| VAD启动阈值 | 900 | PCM16样本绝对值平均能量 |
| 启动保持时间 | 128ms | 需要连续两个 64ms高能量块 |
| pre-roll | 200ms / 6400 bytes | 真实环形 PCM，不是零填充 |
| 尾静音阈值 | 300 | 低于等于该值累计尾静音 |
| 尾静音目标 | 200ms | 受块边界影响通常约 256ms发送 utterance_end |
| 单轮最长录音 | 4s | 达到上限也会结束本轮 |
| 本地 VAD等待窗口 | 3s | 窗口超时不上传、不创建 ASR、不播提示 |

3 秒 VAD窗口超时后会重新打开本地麦克风监听，但不会重复执行机器人播放后的 200ms回声保护。游戏 WebSocket始终保持。

## 4. 空识别提示规则

确认 VAD后立即进入 active turn：

```text
utterance_start
→ 上传200ms pre-roll和实时Opus
→ 尾静音达到条件
→ utterance_end
→ 等待ASR最终结果
```

只有以下空识别类错误允许播放在场提示：

```text
empty_decoded_audio
asr_empty_text
asr_no_final_text
```

处理顺序：

```text
关闭当前active turn和ASR
→ 从VAD确认时刻算，至少达到1.5秒
→ 播放本地静态PCM：“你还在吗？”
→ 不关闭WebSocket、不清除游戏状态
→ 播放结束后200ms回声保护
→ 回到本地VAD
```

同一个等待周期最多播放一次“你还在吗”。后续空识别只执行 `action=silent_rearm`，防止环境噪声造成重复播报。用户完成一个可用回合后，提示标记才会重置。

解码、协议、网络和其他可恢复错误不会播放“你还在吗”，继续沿用单轮错误隔离和静默 rearm。

## 5. 三层空闲退出

### 5.1 提示后的30秒期限

```text
“你还在吗？”播放完成
→ 30秒内没有新的确认VAD
→ 播放“那我们下次再玩吧。”
→ 发送idle_exit
→ 清理当前device_id游戏状态
→ 关闭游戏WebSocket
→ 恢复WakeNet
```

30 秒内出现确认 VAD会暂停该 no-VAD期限并进入 active turn。若该回合仍为空，回到 VAD后重新获得 30 秒，但不会重复播放“你还在吗”。

### 5.2 普通等待的60秒期限

机器人正常回复播放结束后，如果 60 秒完全没有确认 VAD，则不创建 ASR，直接播放退出提示并执行相同 `idle_exit` 流程。

### 5.3 180秒硬期限

距离上一次可用回合达到 180 秒时执行硬退出。该期限不会被空 ASR、纯噪声或协议错误重置，防止环境噪声反复触发 VAD而让游戏永久存活。

## 6. idle_exit协议和设备隔离

板端在 WebSocket idle 状态发送：

```json
{
  "type": "idle_exit",
  "event_id": "idle-<timer>-<sequence>",
  "reason": "no_vad_after_presence_prompt"
}
```

云端回复：

```json
{
  "type": "idle_exit_ack",
  "event_id": "同一事件ID",
  "device_id": "连接的设备ID",
  "skill_name": "idiom_game",
  "skill_active": false,
  "end_skill_state": true,
  "cleared": true
}
```

- `/api/v5/realtime/idiom-game/opus-stream` 现在要求必填 `X-Device-ID`，没有默认共享设备 ID。
- 清理目标只取连接头中的设备 ID，忽略客户端 JSON里可能伪造的 `device_id`。
- 清理是幂等的；状态已经不存在时 ACK返回 `cleared=false`。
- 板端最多等待 ACK 2秒。ACK超时或连接已经断开时仍会退出本地游戏并恢复 WakeNet，云端内存状态最终由原有 TTL回收。

## 7. 本地静态音频

| 文件 | 文本 | 大小 | 格式 |
|---|---|---:|---|
| `idiom_game_presence_1.pcm` | 你还在吗？ | 30,720 bytes | PCM16LE / 16kHz / mono |
| `idiom_game_idle_exit_1.pcm` | 那我们下次再玩吧。 | 53,760 bytes | PCM16LE / 16kHz / mono |

两段音频由云端已经配置的 DashScope/Qwen realtime TTS一次性预生成并写入 SPIFFS。运行时不调用 TTS。两者均为偶数字节且不超过板端本地提示的 64KiB读取上限。

## 8. 关键串口日志

空识别首次提示：

```text
idiom_game_ws turn_error ... error_code=asr_empty_text recoverable=1 action=keep_socket
retry_prompt event=start reason=idiom_game_presence path=/spiffs/idiom_game_presence_1.pcm
idiom_game_turn_recoverable ... action=presence_prompt_then_vad_rearm
```

同周期再次空识别：

```text
idiom_game_turn_recoverable ... action=silent_rearm
```

最终退出：

```text
retry_prompt event=start reason=idiom_game_idle_exit path=/spiffs/idiom_game_idle_exit_1.pcm
idiom_game_ws idle_exit event_id=... reason=no_vad_after_presence_prompt
idiom_game_idle_exit device_id=... reason=... event_id=... ack=1 action=restore_wakenet
```

## 9. 自动验证结果

- 新增设备隔离、WebSocket ACK、必填设备 ID、提示状态机和 PCM资源测试均执行了 RED→GREEN。
- 未过滤全量测试：`293 passed, 19 skipped, 1 known failure, 49 subtests passed`。
- 精确排除该既有断言后：`293 passed, 19 skipped, 1 deselected, 49 subtests passed`。
- voice-skills、Opus、ESP guard和资源集合：`111 passed, 19 skipped, 24 subtests passed, 1 known failure`。
- 唯一失败仍是业务修改前遗留的 Volcengine默认值断言；当前预期 provider 是 DashScope，没有修改或隐藏该失败。
- realtime API、realtime smoke和静态音频目录：`72 passed, 5 subtests passed`。
- ESP-IDF v5.5.4完整 build成功。
- 应用镜像：`0x1c3d70 bytes`；最小 3MiB app分区仍有 `0x13c290 bytes`，约 41%空闲。
- 编译仅有项目原有未使用 OTA符号警告，没有本功能新增编译警告或错误。

## 10. 尚需硬件验收

1. 先部署云端 Python代码并重启 `18111`，确认 healthz和成语 WebSocket smoke。
2. 再烧录本地新固件；云端未更新前不要烧录这个版本，否则板端 `idle_exit` 收不到 ACK。
3. 制造一次很短的杂音或空识别，确认只播放一次“你还在吗”，WebSocket连接不变。
4. 提示后 30 秒不说话，确认播放退出提示、发送 `idle_exit` 并恢复“小明同学”。
5. 正常机器人回复后完全安静 60 秒，确认不创建 ASR并自动退出。
6. 在“你还在吗”后 30 秒内说正确成语，确认取消退出并继续游戏。
7. 连续完成两轮、显式退出，再执行普通咖啡问答，确认既有链路不回归。

在硬件实测前，代码和自动验证状态适合进入“待部署验收”，但尚未提交、推送、部署或烧录。
