# 成语接龙音频收尾与自建 TTS 当前状态

日期：2026-07-17
工作区：`D:\20260709_Tiny_Machine_Robot-merge`
分支：`merge`
基线提交：`a34f27b feat: add fixed idiom rescue budget`

## 已批准结果

人工试听已批准以下固定参数：

```text
provider: self_hosted
service: ws://127.0.0.1:18122/tts/realtime
model: qwen3-tts-base-1_7b
voice: clone_coffee_20s_v1
tempo factor: 0.9
trailing silence: 500ms
format: 16kHz / mono / signed PCM16LE WAV
```

固定素材共14条，全部保存在云端，不再生成或安装板端成语提示PCM。`presence`、`retry` 和 `idle_exit` 由板端请求云端静态音频端点播放。

## 运行时规则

### 固定语句

所有 `idiom_game/*` 固定语句启动校验要求至少500ms安全静音尾。源音频、清单哈希和格式任一无效时不得安装或播放。

### 成语语音

29,493条 `idioms/*` 源文件保持原样，不批量改写。正常接龙、重复和开场拼接只在最终合并PCM末尾追加500ms零采样：

```text
开场：start固定PCM + 原成语PCM + 500ms零PCM
后续：原成语PCM + 500ms零PCM
固定提示：固定PCM自身已有500ms，不重复追加
```

拼接不裁剪、不淡化、不交叉、不重叠，也不检查或改变成语源PCM内容。

### 动态TTS

实时咖啡回答和旧任务WAV封装均只允许使用自建18122服务。整条动态回复只在所有文本片段完成后追加一次500ms，不在每个语义片段后追加。自建服务不可用时返回明确错误，不回退DashScope TTS。DashScope仍用于ASR与LLM。

## 成语库尾部诊断

对29,493条成语只读扫描得到：

| 项目 | 结果 |
|---|---:|
| 格式无效 | 0 |
| 尾静音中位数 | 42.812ms |
| 尾静音少于20ms | 6,337 |
| 尾静音少于80ms | 28,587 |
| 尾静音少于200ms | 29,493 |
| 完全没有尾静音 | 353 |
| 末端RMS大于500的硬切高风险条目 | 82 |

`上善若水.wav` 时长1.44秒、原尾静音约32ms，DashScope ASR能识别完整“上善若水”。人工试听确认在其后追加500ms即可消除缺字听感，因此全库采用运行时追加，不增加约944MB的重复零PCM存储。82条硬切高风险条目后续可单独人耳复核并按需用自建TTS重生成。

## 已批准固定素材清单

候选目录：

```text
远端：/tmp/idiom_self_hosted_fixed_09_500ms_20260717/output
本地：%TEMP%\idiom_self_hosted_fixed_09_500ms_20260717\output
```

| segment_id | WAV字节 | 安静尾 | SHA-256 |
|---|---:|---:|---|
| `idiom_game/start` | 143424 | 540ms | `85e6c85e4d89da8ceaea08342142db4a807397ccbd2b9541487bddced82a8901` |
| `idiom_game/presence` | 41114 | 540ms | `96fe6bb56fb6e242418b7874b9a640d218c548bc86c5cb2fe3344270f56be6f1` |
| `idiom_game/idle_exit` | 80608 | 610ms | `a52f0ed74b29001cc49ae86d26cc34a93390f8ffe9ad4ec362805a04945fb40d` |
| `idiom_game/robot_no_reply_user_win` | 130436 | 610ms | `1d24c94d583f395ab5e0d5a767b155bd15036f140bf270c3ff9a2607dfc2a289` |
| `idiom_game/challenge_win` | 87618 | 590ms | `07306f8f5f6330998753b1b3fe2543d38f1d1c3e35783cde35150dddcb479145` |
| `idiom_game/mode_easy` | 199012 | 640ms | `5428163bd1a836b3fc1b46f7d96678446778fbd68a66d97f961c61c73d77f142` |
| `idiom_game/mode_normal` | 196018 | 710ms | `f9c004d816f8bb6dd1675d38c1510c1cc54b1ccf33898dfc6a2e29b6d325f857` |
| `idiom_game/mode_hard` | 202630 | 920ms | `37bb3329d8dbc7e9c4cbb9597689e1b92e4621e9b453997404963ff04cec5f87` |
| `idiom_game/mode_full` | 213926 | 700ms | `90e563fd6a9b336fff04ca7f3e2d62c7f1fd4bd51fef442afb89004428a466e8` |
| `idiom_game/exit` | 133708 | 640ms | `91a753ec0b3b83f9d96e415ab53df9551913de36e7b1b01920ff32c89696bd83` |
| `idiom_game/continue_prompt` | 183102 | 540ms | `c048071b9377e5a44b3791d8ad9037c08a9073b9c08c6dcea56f4a7e37b02825` |
| `idiom_game/retry` | 89374 | 520ms | `1b625cd41a3653b1a24087f59ca1e629e05985678c3e1c0a1d16dba76ad64c27` |
| `idiom_game/not_found` | 191618 | 550ms | `e9df345376645b3195241740778604d4c1847fcd7197377cbc14ffc45ff99f7e` |
| `idiom_game/static_error` | 123328 | 650ms | `8ca7af3757c4e21da9cc309a14692d38c9c02b57d2f5528f57c3e3551c8cb5b1` |

清单已由 `scripts/prepare_idiom_fixed_audio.py validate` 校验通过，14条均为16kHz、单声道、PCM16，且哈希匹配。

## 部署边界

- 14条云端生产固定素材已按清单哈希原子安装；原有12条文件备份在 `/home/intern2/backups/20260709_Tiny_Machine_Robot/idiom_game_before_selfhost_09_500ms_20260717`。
- 安装后18111 `/healthz` 返回API、Redis、SQLite、ASR、LLM和TTS全部 `ok`。
- 本地代码尚未提交或推送。
- 云端18111尚未用本轮代码重启；因此500ms成语运行时后置静音和新provider仍需代码部署后生效。
- 板端尚未用本轮代码重新编译烧录。
- `esp_idf_demo/main/config.h`、本地IP、Wi-Fi和设备ID不得提交。
- 完整验证中，旧的“默认ASR必须为Volcengine”断言按既有过时失败单独记录，实际默认ASR保持DashScope。
