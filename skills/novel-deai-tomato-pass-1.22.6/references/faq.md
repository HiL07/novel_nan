# 常见问题 FAQ（集中答疑，省得翻多个文档）

本文件是 `novel-deai-tomato-pass` 的**统一答疑入口**。遇到问题先在这里找，找不到再看
`SKILL.md` 的「文件清单」定位对应参考文档或脚本。

> 所有脚本报错现在都是「⚠️ 标题 / 原因 / 怎么修」三段式中文提示（见 `scripts/errkit.py`）。
> 看到「怎么修」就照做，不用去读 traceback。

---

## 1. 安装 / 部署相关

**Q：运行提示 `ModuleNotFoundError: No module named 'docx'`？**
A：依赖没装。在技能目录下跑：
- Windows：`setup.bat`
- macOS / Linux：`./setup.sh`
（会自动建 `.venv` 并装好 `python-docx` + `Pillow`。）已装过就重跑一次。

**Q：提示缺 `Pillow`？**
A：封面客观指标核查才需要 Pillow。同样跑 `setup.bat` / `setup.sh`；或 `python -m pip install Pillow`。
不装也能用——只是 `--cover` 封面核查那一步会优雅跳过，去 AI 味主流程不受影响。

**Q：平台不让跑 .bat / .sh 怎么办？**
A：手动建 venv 装依赖后，直接用 `python scripts/<脚本名>.py [参数]` 跑，效果完全相同
（本 skill 无任何硬编码路径）。详见 SKILL.md「前置条件」的「无脚本入口时的兜底」。

---

## 2. 运行报错怎么查

**Q：报错看不懂？**
A：现在所有脚本出错都会打印 `⚠️ 标题 / 原因 / 怎么修` 三段。先看「怎么修」那行照做。
如果还不行，把整段红字（含最后「技术细节」）发给我，我帮你定位。

**Q：源文件打不开 / 提示「文件不是有效的 .docx 或已损坏」？**
A：确认源文件是 Word「另存为」的 `.docx`，不是 `.doc` / `.txt` / 压缩包改的后缀；
从微信 / 网盘下载的可能损坏，重新下载一次。本 skill **绝不改写你的原文件**，但它需要能正常读。

**Q：提示「文件被占用 / PermissionError」？**
A：关掉正在打开它的 Word / WPS / 资源管理器，或把文件复制到别的目录再跑。

**Q：流水线某一步标了 [X]（失败）？**
A：看 `99_PIPELINE_SUMMARY.md` 里的「⚠️ 执行中遇到的问题」，每一步都给了原因与处理建议；
单步失败**不会阻断**后续步骤，已生成的文件照常可用。根因多半是源文件问题，先按提示修源文件再重跑。

---

## 3. 封面 / 版权（为什么还要我确认）

**Q：都自动化了，为什么封面还要我点？**
A：封面**图的内容**（有没有真人肖像、第三方 IP、敏感地标）脚本看不见，只能你确认；
但**客观指标**（尺寸 / 格式 / 宽高比 / 文件大小 / 是否纯色默认模板）已由 `cover_check.py` 自动测好。
你真正要动的就 3 项：真人肖像 / 第三方 IP / 政治敏感地标——点一下即可。

**Q：版权为什么要我查？**
A：`copyright_scan.py` 只挖**正文文本**里的疑似侵权引用（明星名 / IP / 歌词 / 同人 / 商标），
给出候选让你核查；**跨库版权比对、时政敏感库比对**本 skill 做不了，需你或外部库确认。
版权问题后果量级大于内容驳回，务必确认。

---

## 4. 去 AI 味 / 过审效果

**Q：能不能一键全自动过审、我啥都不用管？**
A：不能，也不该指望。本 skill 是「高级查找替换 + 结构化 agent/人工 SOP」，**不是一键黑盒**：
机械活（删词 / 换词 / 格式 / 风险扫描 / 封面客观指标）全自动；**深层语义（暧昧暗示、多角关系、
价值观）和封面图内容仍要 LLM 读上下文甚至你拍板**。详情见 SKILL.md「能力边界与适用人群」。

**Q：为什么有些暧昧 / 暗示还是没改干净？**
A：模糊地带（无显式 token 的「暗示性留白」）机器扫不准，效果因书而异。
处理方式：`semantic_scan.py` 挖候选 + `relation_graph.py` 画关系图标多角预警，
交给 agent（LLM）读前后章节判断并改写写回 docx，最后**你抽查**。这是「半自动→低人工」，不是全自动。

**Q：真的能过审吗？过审率多少？**
A：以「常规文本至少 90% 以上过审」为**设计目标**，不承诺单本书 100%——AI 味消除效果因书而异。
深层暧昧暗示等模糊地带，配合高置信自动改写 + 你抽查**可以完全避免**；但封面图内容、
跨库比对、删核心情节这几项本质无法自动化。

**Q：改完会不会把好的文本也改坏？**
A：去 AI 味目标是「像人写、有作者声纹」，不是清空所有 AI 词；改动率压到语言润色级（< 10%）。
每次改完有 15 项内置测试兜底，防止规则改动把已过审文本改坏——改脚本后先 `run_tests.bat` 全绿再交付。

---

## 5. 只想跑机械流程 / 快速上手

**Q：我没耐心一步步看，怎么最快用？**
A：一条命令：
```
run.bat scripts/pipeline.py <你的小说.docx> --quick [--names 男主,女A,女B] [--cover 封面图路径]
```
汇总报告只列**不可自动化**的 3 件事（封面点 3 下 / 核心情节决策 / 抽查），其余标「已搞定」。

**Q：只想看某一步的报告？**
A：每个扫描器都能单独跑，参数见 SKILL.md「文件清单」（如 `semantic_scan.py`、
`copyright_scan.py`、`cover_check.py`、`wiki_signs_scan.py`），输出各自的 `.md` 报告。

**Q：想看「改前 vs 改后」长什么样？**
A：见 `references/before_after_examples.md`，含去 AI 味 / 语义精修 / 版权扫描的真实 before→after 片段。

---

## 6. 文件速查

| 想做的事 | 看哪里 |
|---|---|
| 了解能力边界、适不适合我 | SKILL.md「能力边界与适用人群」 |
| 平台怎么判定 AI 产出 / 红线 | `references/tomato_ai_detection.md` |
| 审核类别与修改方向 | `references/tomato_review_rules.md` |
| 8 万字推荐评估自查 | `references/tomato_80k_evaluation.md` |
| 评估不过怎么改 | `references/tomato_eval_fix.md` + `scripts/eval_fix_check.py` |
| 大流量获取 | `references/tomato_traffic_growth.md` |
| agent 语义精修闭环协议 | `references/agent_semantic_rewrite.md` |
| L3 精修模板 | `references/llm_rewrite_sop.md` |
| 人工处理（机器做不了的 5 类） | `references/manual_fix_sop.md` |
| 改前改后示例 | `references/before_after_examples.md` |
| 版本变更 | `CHANGELOG.md` |
