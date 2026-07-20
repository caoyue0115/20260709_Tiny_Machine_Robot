# 成语常用度分类

成语接龙保留 `idioms.json` 的 29,493 条作为用户答案全集。机器人只主动使用 A、B 档，优先 A 档；C 档可以被用户答出，但不会由机器人主动播报。

## 数据来源

- [义务教育常用词表（草案）](https://nclds.xmu.edu.cn/ywjy)：面向母语学习者，15,114 个词目中有 2,578 个四字词。查询接口有每日 300 词限制，因此只作为可增量缓存的强证据，缺失不等于生僻。
- [现代汉语常用词表（草案）](https://www.moe.gov.cn/ewebeditor/uploadfile/2015/01/13/20150113085920115.pdf)：教育部、国家语委发布的 56,008 条频序词表。构建时使用公开转录，并在 `sources.json` 记录文件 SHA-256。
- [BCC 语料库](https://bcc.blcu.edu.cn/help.html)：分别使用多领域、新闻、文学、对话词频，不直接比较不同频道的原始次数，而是使用跨频道命中和频道内阈值。
- [SUBTLEX-CH](https://www.ugent.be/plone_portal/pp/experimentele-psychologie/en/research/documents/subtlexch/overview.htm)：基于 3,354 万字幕词的日常语言频率和语境分布。
- [小学生常用成语辅助表](https://www.plecoforums.com/threads/%E5%B0%8F%E5%AD%A6%E7%94%9F%E5%B8%B8%E7%94%A8%E6%88%90%E8%AF%AD%E5%A4%A7%E5%85%A8-a-huge-list-of-cheng-yu-flashcards.5366/)：非官方补充来源，只有同时得到至少两个语料频道支持时才能升为 A 档。
- [GF 1001-2001 第一批异形词整理表](https://www.moe.gov.cn/jyb_sjzl/ziliao/A19/201001/t20100115_75687.html)：初始化非推荐异形黑名单。

## 分档规则

A 档表示机器人首选。义务教育 1-3 学段词直接进入 A；小学辅助表词需要至少两个语料源支持；现代常用词还需要较高频序和至少三个语料源支持；没有词表支持时，必须在四个以上语料源出现并有日常语料命中。

B 档表示机器人兜底。它包括义务教育第 4 学段、小学辅助表、现代词表中频序较高的词，以及在多种语料中达到最低频率门槛的词。只在单一新闻或文学语料中偶发的词不会进入 B。

C 档是用户可答、机器人禁用。无充分证据的词、极低频词和人工黑名单词都在此档。`config/idiom_usage_overrides.json` 的人工结论优先于所有自动证据；LLM 只用于提出待复核候选，不参与运行时判断。

## 构建和审计

首次构建会下载缺失的公开语料：

```powershell
python scripts/build_idiom_usage_catalog.py --download-sources
```

需要逐日补充教育词表缓存时执行：

```powershell
python scripts/build_idiom_usage_catalog.py --fetch-education --education-query-limit 300
```

运行时数据写入 `src/voice_skills/idiom_usage.json`，覆盖统计写入 `data/idiom_usage/report.json`，来源 URL、大小和哈希写入 `data/idiom_usage/sources.json`。重建后必须运行：

```powershell
python -m pytest tests/test_build_idiom_usage_catalog.py tests/test_idiom_usage_catalog.py -q
```
