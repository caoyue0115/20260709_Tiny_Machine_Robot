# 成语接龙 15+10 秒尝试余额现状报告（2026-07-16）

## 1. 版本与范围

- 工作区：`D:\20260709_Tiny_Machine_Robot-merge`
- 分支：`merge`
- 功能基线：`b777385 feat: add idiom game noise circuit breaker`
- 本次只修改板端游戏计时、游戏专用 VAD 等待接口、静态守卫和文档。
- 云端 WebSocket协议、`device_id`、`turn_id`、DashScope ASR、TTS provider和普通咖啡单轮链路均不修改。
- `esp_idf_demo/main/config.h`、`esp_idf_demo/sdkconfig.multinet_eval` 和本地 bundle 不属于本次功能范围，不得提交。

## 2. 最终产品规则

每次机器人给出有效游戏回复并播放完成后，开始一轮新的尝试周期：

```text
15秒基础余额
+ 首次挽救提示最多增加一次10秒
= 每轮最多25秒用户交互预算
```

用户交互预算包括：

```text
本地VAD等待
VAD触发后的录音
等待ASR final和本轮结果
```

以下时间不扣预算：

```text
机器人回复或提示音播放
播放完成后的200ms回声保护
idle_exit ACK等待
```

### 2.1 完全静默

```text
有效回复播放完成
→ 200ms回声保护
→ 本地VAD等待累计15秒
→ 播放“你还在吗？”
→ 增加一次10秒补救余额
→ 仍无有效结果，余额耗尽
→ 播放“那我们下次再玩吧。”
→ idle_exit并恢复WakeNet
```

墙钟时间会额外包含两段提示音和回声保护，但有效尝试预算固定为25秒。

### 2.2 基础阶段首次空或无效

```text
15秒基础阶段内VAD触发
→ 录音与ASR也继续扣除当前余额
→ empty / invalid / off_topic
→ 屏蔽服务器无效回复音频
→ 本地只播放一次“我没听清，请再说一次”
→ 在剩余基础余额上增加一次10秒
→ 进入补救阶段
```

例如第3秒得到无效结果，余额约为12+10=22秒；已经用掉的3秒不会丢失。第12秒得到无效结果，余额约为3+10=13秒。因此两条路径的用户交互预算上限都仍是25秒。

如果 active turn 在基础余额即将耗尽时开始，录音或ASR等待造成的超时保留为负余额。补救10秒先抵扣这段债务，不能通过慢ASR把总预算延长。

如果这段超时债务已经用完新增的10秒，板端会跳过“我没听清”，直接在安全边界执行退出，避免连续播放“我没听清”和“那我们下次再玩吧”。

### 2.3 补救阶段持续噪声

```text
补救阶段VAD反复触发
→ 每轮录音和ASR继续扣同一份余额
→ empty / invalid / off_topic全部静默
→ 不重复提示
→ 不重置、不刷新、不增加余额
→ 余额耗尽后退出
```

这样外界噪声不会让机器人反复播报“我没听清”，也不能无限产生ASR费用。只有 `meaningful` 才能取消退出并开启新的15秒周期。

### 2.4 有效结果与主动退出

| 结果 | 板端行为 |
|---|---|
| `meaningful` | 有效成语、重复、难度切换；播放正常静态回复，重置为新15秒周期 |
| `empty` | 基础阶段本地提示一次并进入补救；补救阶段静默 |
| `invalid` | 同 `empty`，不播放服务器无效提示 |
| `off_topic` | 同 `empty`，不播放服务器无关提示 |
| `exit` / `end_skill_state=true` | 播放必要结束音频并立即结束，不等待预算 |
| 缺失 `turn_outcome` | 兼容旧云端，视为成功轮次并重置15秒 |
| 基础设施错误 | 不冒充“没听清”，不增加预算；已经消耗的时间仍扣除 |

## 3. 状态机

```text
ROBOT_PLAYBACK
  → ECHO_GUARD（200ms，不扣余额）
  → BASE_VAD（15s余额）

BASE_VAD --无VAD且余额耗尽--> PRESENCE_PROMPT
PRESENCE_PROMPT --加10s一次--> RESCUE_VAD

BASE_VAD --VAD/ASR非有效--> MISHEARD_PROMPT
MISHEARD_PROMPT --剩余基础余额+10s一次--> RESCUE_VAD

RESCUE_VAD --VAD/ASR非有效--> RESCUE_VAD（静默，继续扣余额）
BASE_VAD/RESCUE_VAD --meaningful--> ROBOT_PLAYBACK（新15s）
BASE_VAD/RESCUE_VAD --exit--> GAME_END
RESCUE_VAD --余额耗尽--> IDLE_EXIT --> WakeNet
```

余额不足时不会开始新的 ASR。如果某轮已经在余额变为零前启动，则允许它完成，避免破坏 Opus、ASR final和 active turn资源；有效结果仍可恢复，否则在下一个安全边界退出。

## 4. VAD与ASR边界

| 参数 | 当前值 | 说明 |
|---|---:|---|
| 播放后回声保护 | 200ms | 回声期间不允许触发上传，不扣尝试余额 |
| VAD内部 armed 保护 | 150ms | 麦克风刚打开时先稳定；计入VAD等待预算 |
| VAD启动阈值 | 900 | PCM16块平均绝对能量 |
| VAD启动保持 | 128ms | 连续高能量达到该时长才确认开口 |
| 真实 pre-roll | 200ms | 只存在板端环形缓冲；VAD确认后才上传 |
| 尾静音阈值 | 300 | 小于等于该能量累计为静音 |
| 尾静音结束 | 200ms | 达到后发送 `utterance_end` |
| 单轮录音上限 | 约4s | 没有200ms尾静音时仍强制结束本轮录音 |
| 单次VAD检查窗 | 最多3s | 最后一窗缩短到当前剩余余额 |

准确资源链路：

```text
游戏WebSocket持续连接
→ idle时云端无ASR、板端不上传音频
→ 本地VAD确认
→ utterance_start创建本轮ASR
→ 上传200ms pre-roll与实时Opus
→ 200ms尾静音或约4秒上限
→ utterance_end停止输入
→ 等待asr_final或超时
→ 销毁本轮ASR
→ WebSocket继续空闲
```

## 5. 设备与轮次隔离

- 游戏状态仍由云端按 `device_id`保存，设备断线重连不与其他设备串状态。
- 每轮继续携带唯一 `turn_id`；迟到的 `done`不能被下一轮接收。
- 自动退出发送唯一 `event_id` 和当前连接的设备身份。
- 云端 `idle_exit`清理保持幂等；板端最多等 ACK 2秒，无论 ACK是否返回都清除本地上下文、关闭游戏WebSocket并恢复WakeNet。
- 退出后用户必须重新说“小明同学”才能开始新的普通交互或游戏。

## 6. 静态音频

| 文件 | 文本 | 运行方式 |
|---|---|---|
| `idiom_game_presence_1.pcm` | 你还在吗？ | 板端 SPIFFS静态播放 |
| `idiom_game_misheard_1.pcm` | 我没听清，你再说一次。 | 板端 SPIFFS静态播放，每轮最多一次 |
| `idiom_game_idle_exit_1.pcm` | 那我们下次再玩吧。 | 板端 SPIFFS静态播放 |

本次没有新增音频素材，成语模式运行时仍不使用动态 TTS。

## 7. 成本边界

- 完全静默的25秒尝试期只有本地VAD，不创建云端ASR。
- 噪声只有达到启动阈值并连续保持128ms才会创建一次ASR。
- 每个 active turn由200ms尾静音或约4秒录音上限结束。
- active turn等待也扣总余额；补救阶段噪声不能刷新时间。
- 因此单轮游戏等待期不会因连续噪声无限产生ASR请求或音频上传。

## 8. 自动验证与部署状态

TDD与回归证据：

```text
新增“超时债务”守卫：先失败，最小实现后通过
新增“余额耗尽时不连续播放两条提示”守卫：先失败，最小实现后通过
ESP静态守卫：17 passed, 1 deselected
聚焦云端/板端回归：173 passed, 19 skipped, 1 deselected, 29 subtests passed
未过滤全量：298 passed, 19 skipped, 1 known failure, 49 subtests passed
精确排除既有断言：298 passed, 19 skipped, 1 deselected, 49 subtests passed
ESP-IDF 5.5.4 build：成功
```

唯一未过滤失败仍是业务修改前遗留的 Volcengine默认值断言：当前产品明确使用 DashScope，不得为了通过旧测试恢复 Volcengine。该失败已单独记录，没有计为本次功能回归，也没有隐藏其他失败。

最终应用镜像：

```text
esp_idf_demo.bin = 0x1c4a20 bytes
最小app分区 = 0x300000 bytes
剩余 = 0x13b5e0 bytes（41%）
```

编译只有项目原有的未使用 OTA符号警告，没有本次功能新增的编译错误。

当前代码尚未提交、推送、部署或烧录。

部署时需要同时更新协议兼容的云端基线与新固件；本次新增行为本身位于板端，所以至少必须重新 `idf.py build`、`flash`、`monitor`。普通云端服务若已经是包含 `turn_outcome` 和 `idle_exit` 的版本，本次不需要额外云端代码变更。

## 9. 实机验收清单

1. 进入四种成语模式，确认正常接龙无需再次唤醒。
2. 有效回复后完全静默：约15秒播放“你还在吗？”，再给10秒有效尝试预算后退出。
3. 基础阶段尽早制造一次空ASR：只播放一次“我没听清，请再说一次”，总有效尝试时间仍约25秒。
4. 在基础阶段较晚制造空ASR：确认未用余额与10秒补救叠加，而不是从无效时刻重新给25秒。
5. 补救阶段持续制造噪声：不再播放“我没听清”，余额仍耗尽并退出。
6. 补救阶段说出有效成语：正常回复，并重新开始15秒基础周期。
7. 说重复或难度切换命令：视为有效结果并重置周期。
8. 说“退出游戏 / 不玩了 / 结束吧”：立即退出；直接说成语不能继续，必须重新说“小明同学”。
9. 自动退出应播放“那我们下次再玩吧”，关闭游戏WebSocket并恢复WakeNet。
10. 普通咖啡问答行为保持不变。
