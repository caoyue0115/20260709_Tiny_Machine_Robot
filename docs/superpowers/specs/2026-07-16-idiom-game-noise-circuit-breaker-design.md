# 成语接龙紧凑空闲退出与噪声熔断设计

日期：2026-07-16
状态：已确认
方案：B（云端轮次语义分类 + 板端噪声熔断）

## 1. 目标

在不持续上传音频、不持续创建云端 ASR、不中断游戏 WebSocket 的前提下，让四种成语游戏模式采用相同且更紧凑的退出节奏：

- 机器人回复播放结束后，25 秒没有 VAD，播放“你还在吗？”。
- 该提示播放结束后，20 秒仍没有 VAD，播放“那我们下次再玩吧。”并退出游戏。
- 一次 VAD 触发后若 ASR 为空，首次播放“我没听清，你再说一次。”，随后重新等待。
- 非有效轮次反复触发 VAD 时不重复播报，且从第一次非有效轮次开始最多 60 秒必须退出。
- 有效成语、重复命令和难度切换会解除熔断并开始新的正常周期。
- 所有自动退出最终关闭游戏 WebSocket、清除当前 `device_id` 游戏状态并恢复 WakeNet；下一次交互必须重新说“小明同学”。

## 2. 非目标

- 不增加说话人识别、声纹或频谱级噪声分类。
- 不改变 WakeNet、MultiNet 命令表、Opus 格式或 ASR provider；DashScope 仍是预期 ASR provider。
- 不改变普通咖啡问答的单轮链路。
- 不在成语模式中启用运行时动态 TTS。
- 不删除现有 15 分钟游戏上下文 TTL；本设计只替换 30/60/180 秒空闲策略。

## 3. 云端轮次结果协议

成语游戏 WebSocket 的成功 `done` 新增可选字段：

```json
{
  "type": "done",
  "turn_id": "device-turn-id",
  "skill_name": "idiom_game",
  "skill_active": true,
  "end_skill_state": false,
  "audio_stream_url": "...",
  "turn_outcome": "meaningful"
}
```

`turn_outcome` 枚举为：

| 值 | 含义 | 示例 | 是否解除熔断 |
|---|---|---|---|
| `meaningful` | 有效、明确的游戏行为 | 成功接龙、重复、简单/困难切换 | 是 |
| `invalid` | 已识别出文本，但未形成有效游戏行为 | 未知成语、重复成语、接错拼音、低置信度判断 | 否 |
| `off_topic` | 与当前成语游戏无关 | 自由问答、背景电视语句 | 否 |
| `exit` | 游戏本轮结束 | 主动退出、LLM exit、胜负结束 | 立即退出 |

云端从现有 `idiom_event`、`idiom_result` 和最终游戏状态确定结果，不增加第二次 LLM 请求。`matches_expected_pinyin` 仍只用于日志，不参与本字段的可信判定。

板端 MultiNet 在游戏上下文中直接拦截到重复或难度切换时，板端已经知道命令类型，可直接按 `meaningful` 处理，不需要为了取得 `turn_outcome` 再发起 ASR。其规范化文本 session 仍用于取得对应静态回复音频。

空音频不发送成功 `done`，继续复用现有可恢复错误：

```text
empty_decoded_audio
asr_empty_text
asr_no_final_text
```

板端把这三类错误统一当作 `empty` 非有效轮次。解码、网络、协议和 provider 错误保持现有“仅重置当前轮并静默重新 armed”策略，不错误播放“我没听清”。

`turn_outcome` 只加入成语游戏链路，普通 realtime `done` 不变。为兼容云端先部署、板端后烧录的顺序，字段为可选；新版板端遇到字段缺失时保留旧版成功轮次行为并记录兼容日志，遇到未知枚举时按非有效 `invalid` 处理。

## 4. 板端状态与计时器

板端保留现有游戏状态机，并增加相互独立的策略状态：

```text
presence_prompted       是否已播放“你还在吗”
nonmeaningful_prompted  本次熔断周期是否已经播放过非有效轮次提示
normal_idle_deadline    正常回复后25秒无VAD截止
presence_exit_deadline  “你还在吗”后20秒无VAD截止
retry_idle_deadline     非有效轮次后30秒无VAD截止
noise_hard_deadline     第一次非有效轮次起60秒硬截止
```

所有 deadline 使用 `esp_timer_get_time()` 的单调时钟，不使用墙上时间。进入上传、等待 ASR 或播放状态时不在中途强杀资源；截止时间只在重新进入 VAD/idle 边界时判定。因此实际动作可受现有 3 秒 VAD 等待窗口影响，允许约 0～3 秒检查延迟。

### 4.1 正常无 VAD

```text
有效机器人回复播放结束
→ 清除所有熔断标志
→ 200ms 回声保护
→ 本地 VAD armed
→ 启动25秒 normal_idle_deadline
```

25 秒没有 VAD：

```text
播放“你还在吗？”
→ 播放期间禁止VAD上传
→ 200ms回声保护
→ 重新armed
→ 启动20秒 presence_exit_deadline
```

20 秒仍没有 VAD：

```text
播放“那我们下次再玩吧。”
→ 发送idle_exit
→ 最多等待2秒idle_exit_ack
→ 无论ACK是否到达都在本地退出并恢复WakeNet
```

即正常纯静默从机器人回复播放完成起约 45 秒退出，而不是原来的 60 秒直接退出。

### 4.2 首次空 ASR

VAD 触发后仍按现有链路创建本轮 ASR、上传 pre-roll 和实时 Opus。若本轮返回三类空结果之一：

```text
若 nonmeaningful_prompted=false
→ 最早在VAD触发1.5秒后播放“我没听清，你再说一次。”
→ nonmeaningful_prompted=true
→ noise_hard_deadline固定为第一次非有效轮次VAD触发时刻+60秒
→ 提示播放完成后启动30秒 retry_idle_deadline
→ 200ms回声保护后重新armed
```

“你还在吗？”和“我没听清”属于不同语义提示。前者不设置 `nonmeaningful_prompted`；因此用户在 presence 窗口内触发 VAD 但 ASR 为空时，允许再播放一次“我没听清”。

### 4.3 重复噪声与提示抑制

若第一次非有效轮次是成功 `done` 中的 `invalid` 或 `off_topic`，而不是空 ASR，则允许播放该轮云端静态提示一次，并执行与首次空 ASR 相同的熔断初始化：

```text
nonmeaningful_prompted=true
noise_hard_deadline=该轮VAD触发时刻+60秒
清除 normal/presence deadline
提示播放完成后启动30秒 retry_idle_deadline
```

熔断开启后，后续 `empty`、`invalid` 或 `off_topic` 均不得再次播放非有效轮次提示：

```text
重复VAD
→ 本轮按需完成ASR/路由
→ 不播放“我没听清”
→ 对 invalid/off_topic 返回的音频也跳过播放
→ 静默重新armed
→ 重新启动30秒 retry_idle_deadline
→ 不改变 noise_hard_deadline
```

因此：

- 后续完全没有 VAD 时，最后一次非有效轮次后约 30 秒退出。
- 噪声持续反复触发 VAD 时，30 秒安静退出可被活动轮次打断，但 60 秒硬截止永不刷新。
- 到达 60 秒硬截止后，在当前 active turn 和播放安全结束后的第一个 idle 边界退出，不在音频上传或播放中途破坏资源。

提示抑制只限制非有效轮次提示；最终退出提示“那我们下次再玩吧。”仍播放一次。

### 4.4 有效轮次解除熔断

收到 `turn_outcome=meaningful` 且对应 `turn_id` 正确时：

```text
正常播放本轮静态回复
→ presence_prompted=false
→ nonmeaningful_prompted=false
→ 清除 retry_idle_deadline 和 noise_hard_deadline
→ 从播放完成时重新启动25秒 normal_idle_deadline
```

只有有效成语、重复命令和难度切换属于 `meaningful`。空结果、未知成语、接错拼音、重复成语、低置信度、无关内容和错误轮次都不能解除熔断。

### 4.5 显式退出和游戏结束

`turn_outcome=exit` 或现有 `end_skill_state=true` 始终优先：播放云端计划的静态退出/胜负音频后立即关闭游戏 WebSocket并恢复 WakeNet，不等待任何空闲计时器。

## 5. 音频素材

新增板端 SPIFFS 素材：

```text
/spiffs/idiom_game_misheard_1.pcm
文本：我没听清，你再说一次。
格式：16kHz / 单声道 / 16-bit PCM little-endian
```

素材只在开发/部署阶段使用云端已配置的 TTS 生成一次。运行时直接播放 SPIFFS 文件，不调用动态 TTS。素材缺失时使用已有板端通用静态错误提示，但仍必须设置 `nonmeaningful_prompted=true`，防止缺失素材造成无限重播。

## 6. 设备隔离与错误隔离

- 游戏状态继续以连接必需的 `X-Device-ID` 隔离；不信任控制消息体内的 device id。
- `turn_outcome` 只接受与当前 active `turn_id` 匹配的 `done`。
- 迟到 `done`、迟到二进制包和错误 `turn_id` 仅丢弃，不刷新任何 deadline。
- 单轮 ASR、解码或协议错误只销毁 active turn，不清除云端游戏状态、不关闭 WebSocket。
- 基础设施错误不得重置正常、presence、retry 或 noise hard deadline；回到 idle 后继续使用错误前的绝对截止时间，已到期则立即进入对应退出流程。
- 自动退出继续使用唯一 `event_id`，服务端清除操作保持幂等。

## 7. 可观测性

板端至少记录：

```text
turn_outcome
nonmeaningful_prompted
normal/presence/retry/noise_hard deadline命中原因
提示被播放或被熔断抑制
idle_exit reason、event_id、ACK结果
```

自动退出 reason 固定区分：

```text
no_vad_after_presence_prompt
no_vad_after_nonmeaningful_turn
repeated_nonmeaningful_hard_timeout
```

云端记录 `device_id`、`turn_id`、`idiom_event`、`idiom_result` 和导出的 `turn_outcome`，不记录或回显本地 Wi-Fi、IP 配置。

## 8. 测试与验收

先补失败测试，再实现。

云端测试：

- 有效接龙、重复和难度切换的 `done.turn_outcome=meaningful`。
- 未知/重复/接错成语和低置信度为 `invalid`。
- 无关内容为 `off_topic`。
- 退出和胜负结束为 `exit`。
- 普通咖啡 realtime `done` 不增加成语字段。
- `turn_outcome` 不增加 LLM、ASR或TTS请求。

ESP 静态与协议测试：

- 四个模式共用 25 秒 normal、20 秒 presence、30 秒 retry、60 秒 noise hard 常量。
- `cloud_realtime_session_t` 可解析可选 `turn_outcome`。
- 首次空结果引用 `idiom_game_misheard_1.pcm`，重复空结果进入 silent rearm。
- `invalid/off_topic` 在熔断后跳过音频播放且不刷新60秒截止。
- `meaningful` 清除熔断并重启25秒周期。
- 60秒截止不会被重复 VAD 刷新。
- `idle_exit` 仍最多等待2秒 ACK并无条件恢复WakeNet。
- 新 PCM 文件格式和文本清单通过校验。
- `config.h` 和 `sdkconfig.multinet_eval` 不纳入提交。

实机验收：

1. 四种模式中，机器人回复后保持安静，约25秒播放“你还在吗？”，再约20秒播放退出提示并恢复 WakeNet。
2. 单次轻微噪声触发空 ASR，只播放一次“我没听清，你再说一次。”；随后安静约30秒退出。
3. 连续制造噪声触发，机器人不重复播报，第一次非有效轮次后约60秒退出。
4. 熔断期间说出有效成语，正常播放新成语并重新开始25秒周期。
5. 说“退出游戏”立即退出；退出后必须重新说“小明同学”。
6. 普通咖啡问答行为不变。

## 9. 部署顺序

```text
云端先部署兼容的 turn_outcome 协议
→ 重启并验证18111
→ ESP-IDF完整build
→ 使用flash写入应用和SPIFFS
→ monitor实机验收
```

云端先部署时旧板端会忽略新增字段；板端烧录后即可启用完整 B 方案。由于新增 SPIFFS PCM，不能只执行 `app-flash`。

## 10. 已知边界

本设计把“空 ASR、语义无效、无关内容”视作噪声风险，但不做声纹识别。背景电视如果恰好说出一个有效可接成语，仍可能被视为 `meaningful`。解决该极低概率场景需要说话人识别或更复杂声学模型，不纳入当前版本。
