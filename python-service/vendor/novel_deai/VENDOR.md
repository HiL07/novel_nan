# novel_deai（第三方，原样收录）

- 来源：SkillHub `novel-deai-tomato-pass`（小说去 AI 味 + 过番茄审核），https://www.skillhub.cn/skills/user_170e8f72/novel-deai-tomato-pass
- 版本：1.22.6（`_meta.json`）；包内未附许可证文件
- 收录内容：`scripts/`、`references/`、`SKILL.md`、`CHANGELOG.md`、`_meta.json`、`requirements.txt`（未收录 tests / setup / run 脚本）

**不要修改这里的文件。** 项目通过 `app/polish/engine.py` 按纯文本调用其中的函数
（`deai_humanizer.clean`、`auto_rewrite.rewrite_paragraph`、`deai_deep_report.check_chapter`、
`eval_fix_check.check_chapter`、`wiki_signs_scan` / `semantic_scan` / `copyright_scan.scan_paragraph`、
`build_map_wizard.scan_triggers`）。规则不合适时在适配层里过滤或后处理。

升级：用新版本整体替换本目录（保留本文件），跑一遍 `python -m app.polish.engine` 自检，
确认上述函数签名未变（适配层启动时会检查，缺失则检测结果里报错，不影响章节生成）。
