# 成语接龙紧凑退出与噪声熔断现状报告（2026-07-16）

## 1. 当前版本状态

- 工作区：`D:\20260709_Tiny_Machine_Robot-merge`
- 分支：`merge`
- 基础提交：`f0fcd39 feat: add idle exit handling for idiom game`
- 本报告对应的 B 方案代码尚未提交、推送、部署或烧录。
- 云端已部署的是上一版 idle-exit 基线；本版 `turn_outcome` 协议仍需重新部署并重启 `18111`。
- `esp_idf_demo/main/config.h`、`esp_idf_demo/sdkconfig.multinet_eval` 和本地部署 bundle 均未纳入功能改动。
- DashScope 仍是预期 ASR provider，没有恢复 Volcengine。

## 2. 目标行为总览

四种成语游戏模式共用同一套时间策略：

```text
有效机器人回复播放结束
→ 25秒没有VAD
→ 播放“你还在吗？”
→ 再20秒没有VAD
→ 播放“那我们下次再玩吧。”
→ idle_exit
→ 关闭游戏WebSocket并恢复WakeNet
```

VAD触发但 ASR为空：

```text
第一次非有效轮次
→ 播放“我没听清，你再说一次。”
→ 30秒没有新VAD则退出

后续 empty / invalid / off_topic
→ 不再播放非有效提示
→ 静默重新armed
→ 每轮可重新获得30秒安静等待
→ 但第一次非有效轮次起60秒硬截止永不刷新
```

有效成语、重复命令和难度切换会解除熔断，播放正常静态回复并重新开始25秒周期。显式退出和 `end_skill_state=true` 仍然立即结束游戏。

## 3. WebSocket、VAD 与 ASR资源边界

```text
游戏WebSocket：游戏期间持续连接，idle时只有协议心跳
板端麦克风：只为本地能量VAD和200ms pre-roll采样
音频上传：只有确认VAD后才开始
云端ASR：只有utterance_start后才创建
utterance_end：停止音频输入，等待final/超时后销毁本轮ASR
```

播放任何机器人音频期间禁止 VAD上传。播放结束后先执行200ms回声保护，再回到本地 VAD。游戏退出后关闭持续 WebSocket、清除本地游戏上下文并恢复 WakeNet；用户下一次必须重新说“小明同学”。

## 4. 当前VAD参数

| 参数 | 当前值 | 含义 |
|---|---:|---|
| 播放后回声保护 | 200ms | 防止扬声器回声触发上传 |
| VAD内部armed保护 | 150ms | 麦克风刚打开时暂不接受触发 |
| 启动阈值 | 900 | PCM16块平均绝对能量 |
| 启动保持 | 128ms | 高能量必须连续保持 |
| pre-roll | 200ms | 板端真实环形PCM，仅触发后上传 |
| 尾静音阈值 | 300 | 小于等于该能量累计为静音 |
| 尾静音目标 | 200ms | 达到后发送utterance_end |
| VAD等待窗口 | 3s | 只用于周期性检查deadline；超时不上传 |

因此计时器不是持续云端录音：25/20/30/60秒期间云端没有 ASR实例，也没有音频计费。

## 5. 云端 `turn_outcome` 协议

持久游戏 WebSocket 的成功 `done` 新增可选字段：

```json
{
  "type": "done",
  "turn_id": "device-id-...",
  "skill_name": "idiom_game",
  "skill_active": true,
  "end_skill_state": false,
  "audio_stream_url": "...",
  "turn_outcome": "meaningful"
}
```

允许值：

| outcome | 来源 | 板端行为 |
|---|---|---|
| `meaningful` | 有效接龙、重复、难度切换 | 播放回复、清除熔断、重置25秒 |
| `invalid` | 未知/重复/接错成语、低置信度 | 首次播放静态解释，后续熔断静默 |
| `off_topic` | 无关内容 | 首次播放静态提示，后续熔断静默 |
| `exit` | 主动退出、LLM exit、胜负结束 | 播放必要结束音频并退出 |

该字段直接从已有 `idiom_event`、`idiom_result` 和游戏最终状态导出，不增加 LLM请求。普通咖啡 realtime `done` 不包含该字段。

新版板端将字段解析到固定16字节缓冲。字段缺失时按旧云端成功轮次兼容并记录 `action=turn_outcome_compat_legacy`；未知非空枚举按非有效轮次处理。所有 `done` 仍必须匹配当前 active `turn_id`。

## 6. 空ASR与基础设施错误

只有以下可恢复错误属于 `empty`：

```text
empty_decoded_audio
asr_empty_text
asr_no_final_text
```

第一次命中时，从 VAD确认时刻算最早1.5秒后播放“我没听清，你再说一次。”，设置 `nonmeaningful_prompted=true`，并把60秒硬截止锚定在第一次非有效 VAD时刻。

后续空结果记录：

```text
action=nonmeaningful_prompt_suppressed
```

不再播放提示。解码、网络、协议和 provider等基础设施错误不冒充空ASR，不播放“我没听清”，不清除游戏状态，也不获得一份新的空闲期限；回到 idle后继续使用错误前的绝对 deadline。

## 7. 三种软时间路径

### 7.1 正常静默

```text
回复结束后25秒无VAD
→ “你还在吗？”
→ 20秒无VAD
→ no_vad_after_presence_prompt
→ 退出
```

VAD窗口每3秒返回一次，因此实际提醒/退出允许约0～3秒检查延迟，不包含提示音自身播放时间。

### 7.2 单次非有效轮次后静默

```text
首次empty / invalid / off_topic处理完成
→ 30秒无VAD
→ no_vad_after_nonmeaningful_turn
→ 退出
```

`empty`首次播放本地“我没听清”；`invalid/off_topic`首次允许播放服务器已经生成的静态游戏提示。两者共享同一个 `nonmeaningful_prompted`锁，保证一次熔断周期最多只有一条非有效轮次提示。

### 7.3 重复噪声硬截止

```text
第一次非有效轮次的VAD时刻
→ 固定60秒 noise_hard_deadline
→ 后续VAD、空ASR、invalid、off_topic均不得刷新
→ repeated_nonmeaningful_hard_timeout
→ 退出
```

硬截止在两个位置强制检查：

1. 每次准备进入新 VAD等待窗口前。
2. VAD已经检测到声音后、创建下一轮 ASR前。

因此连续噪声即使每次都快速触发 VAD，也无法通过避免3秒等待超时来绕过60秒上限。若截止发生在 active turn或音频播放中，不中途破坏资源，而是在回到首个安全 idle边界时退出。

## 8. 强制退出过程

所有自动退出统一调用同一个板端 helper：

```text
播放“那我们下次再玩吧。”
→ 生成唯一event_id
→ WebSocket发送idle_exit和reason
→ 云端按连接X-Device-ID清除游戏状态
→ 最多等待2秒idle_exit_ack
→ 无论ACK是否成功都清除本地上下文
→ 关闭游戏WebSocket
→ 释放麦克风资源
→ 恢复WakeNet
```

云端清理保持幂等，测试设备没有活动状态时 `cleared=false` 仍是成功 ACK。

## 9. 静态音频

| 文件 | 文本 | 大小 | 格式 |
|---|---|---:|---|
| `idiom_game_presence_1.pcm` | 你还在吗？ | 30,720 bytes | PCM16LE / 16kHz / mono |
| `idiom_game_misheard_1.pcm` | 我没听清，你再说一次。 | 64,924 bytes | PCM16LE / 16kHz / mono |
| `idiom_game_idle_exit_1.pcm` | 那我们下次再玩吧。 | 53,760 bytes | PCM16LE / 16kHz / mono |

新素材由云端已配置的 DashScope/Qwen realtime TTS一次性生成。原始带标点版本超过板端64KiB上限；最终使用相同口语内容、去除生成输入中的停顿标点，并仅裁剪经波形确认的首尾静音，保留约20ms安全余量。运行时只读取 SPIFFS，不调用动态 TTS。

## 10. 自动验证证据

TDD过程：

- 云端 outcome分类测试先因 `SkillResult`缺字段产生预期失败，最小实现后通过。
- WebSocket协议测试先因 `done`缺键产生3个预期失败，实现后通过。
- ESP解析守卫先因结构体缺字段失败，实现后通过。
- PCM素材测试先因文件和清单缺失失败，生成并登记后通过。
- 25/20/30/60状态机守卫先产生4个预期失败，实现后通过。
- 连续噪声硬截止 preflight测试先失败，实现双检查后通过。

最终结果：

```text
聚焦云端/ESP回归：173 passed, 19 skipped, 1 deselected, 29 subtests passed
最终未过滤全量：297 passed, 19 skipped, 1 known failure, 49 subtests passed
精确排除既有断言：297 passed, 19 skipped, 1 deselected, 49 subtests passed
ESP守卫和素材：54 passed, 1 deselected
ESP-IDF 5.5.4 build：成功
```

唯一失败仍是修改前遗留的 Volcengine默认值断言；当前业务明确要求 DashScope，没有修改、隐藏或计为本次回归。

最终应用镜像：

```text
esp_idf_demo.bin = 0x1c4440 bytes
最小app分区 = 0x300000 bytes
剩余 = 0x13bbc0 bytes（41%）
```

编译只有项目原有未使用 OTA符号警告，没有本功能新增错误。

## 11. 部署与实机验收

部署顺序必须是：

```text
提交并推送merge分支
→ bundle传云端
→ 云端应用提交并重启18111
→ healthz与持久游戏WebSocket smoke
→ ESP-IDF完整flash（包含storage.bin）
→ monitor实机验收
```

由于新增 `idiom_game_misheard_1.pcm`，不能只执行 `app-flash`。

最低实机验收：

1. 四种模式分别确认约25秒播放“你还在吗”，再约20秒退出并恢复“小明同学”。
2. 一次空ASR只播放一次“我没听清，你再说一次”，随后安静约30秒退出。
3. 连续制造噪声，后续提示保持静默，第一次非有效轮次后约60秒强制退出。
4. 熔断期间说出有效成语，确认立即解除熔断并重新开始25秒周期。
5. `invalid/off_topic`首次可播必要提示，后续相同噪声不再下载或播放回复音频。
6. 主动说“退出游戏”立即结束；退出后直接说成语无效，必须重新说“小明同学”。
7. 普通咖啡问答行为不变。

当前代码与自动验证已经达到“可建议提交、待部署和硬件验收”状态；尚未执行提交、推送、部署或烧录。
