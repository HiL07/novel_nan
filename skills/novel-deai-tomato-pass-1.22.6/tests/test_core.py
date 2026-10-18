# -*- coding: utf-8 -*-
"""novel-deai-tomato-pass 端到端测试（unittest，零第三方测试依赖）。

运行方式（skill 根目录）:
  Windows: run_tests.bat
  macOS/Linux: ./run_tests.sh
  或任意环境: python tests/run_tests.py

前置: 先运行 setup.bat / setup.sh（或本机已装 python-docx）。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
FIXTURE_MAKER = TESTS / "make_fixture.py"


def py():
    """优先用 .venv，缺失则退回当前解释器（便于未 setup 环境也能跑）。"""
    venv = SKILL_ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    return str(venv) if venv.exists() else sys.executable


def run_script(*args):
    return subprocess.run([py(), *map(str, args)], capture_output=True, text=True,
                          cwd=str(SKILL_ROOT))


def doc_text(path):
    from docx import Document
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


class TomatoSkillTest(unittest.TestCase):
    tmp = None
    src = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="tomato_test_"))
        cls.src = cls.tmp / "sample.docx"
        r = run_script(FIXTURE_MAKER, cls.src)
        assert r.returncode == 0, r.stderr

    def test_01_extract(self):
        out = self.tmp / "extracted.txt"
        r = run_script(SCRIPTS / "extract_docx.py", self.src, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out.read_text(encoding="utf-8")
        self.assertIn("重生之都市王者", text)
        self.assertIn("第一章 重回都市", text)
        self.assertIn("第五章 前路", text)

    def test_02_wizard(self):
        """映射向导：自动产出通用安全层 + 候选层 + 说话人清单。"""
        draft = self.tmp / "draft_map.json"
        report = self.tmp / "wizard.md"
        r = run_script(SCRIPTS / "build_map_wizard.py", self.src, "--map", draft, "--out", report)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(draft.read_text(encoding="utf-8"))
        for key in ("bulk", "candidates", "speakers"):
            self.assertIn(key, d, f"草稿缺 {key}")
        self.assertTrue(d["bulk"], "AUTO_SAFE 命中词应进入 bulk")
        self.assertTrue(any("胸部" in old for old, _ in d["bulk"]), f"胸部词应进 bulk: {d['bulk']}")
        self.assertIn("上床", json.dumps(d["candidates"], ensure_ascii=False), "上床应在候选层")
        names = [s.get("name") for s in d["speakers"]]
        self.assertIn("苏晚晴", names, f"说话人清单缺苏晚晴: {names}")
        self.assertTrue(report.exists() and report.stat().st_size > 0, "扫描报告未生成")

    def test_03_wizard_draft_consumable(self):
        """草稿可直接被 reframe 消费：通用安全层自动生效，候选层保留待人工确认。"""
        draft = self.tmp / "draft_map.json"
        out = self.tmp / "reframed_draft.docx"
        r = run_script(SCRIPTS / "build_map_wizard.py", self.src, "--map", draft)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_script(SCRIPTS / "reframe_novel.py", self.src, out, "--map", draft,
                       "--title-new", "重生之都市王者（修订版）")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = doc_text(out)
        self.assertNotIn("饱满的胸部", text, "AUTO_SAFE 替换应生效")
        self.assertIn("上床", text, "候选层未定稿应保留（预期行为）")
        from docx import Document
        self.assertEqual(Document(str(out)).core_properties.title, "重生之都市王者（修订版）",
                         "书名属性应被写回")

    def test_04_reframe_custom_map(self):
        """定稿自定义映射：bulk 替换全部生效。"""
        m = {"bulk": [["上床", "同床共枕"], ["四个女人", "三位挚友"], ["共侍一夫", "一同效命"]],
             "chapter_swaps": {}, "title_new": "新书名"}
        mp = self.tmp / "custom_map.json"
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        out = self.tmp / "reframed_custom.docx"
        r = run_script(SCRIPTS / "reframe_novel.py", self.src, out, "--map", mp)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = doc_text(out)
        for bad in ("上床", "四个女人", "共侍一夫"):
            self.assertNotIn(bad, text, f"{bad} 应被替换")

    def test_05_humanizer(self):
        """L1 机械层：应产生文本改动。"""
        out = self.tmp / "humanized.docx"
        r = run_script(SCRIPTS / "deai_humanizer.py", self.src, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists(), "输出 docx 未生成")
        self.assertNotEqual(doc_text(self.src), doc_text(out), "去AI机械层应产生文本改动")

    def test_06_deep_report(self):
        """L2 诊断层：产出含 MUST/WARN 分级的逐章报告。"""
        report = self.tmp / "deep.md"
        r = run_script(SCRIPTS / "deai_deep_report.py", self.src, "--out", report)
        self.assertEqual(r.returncode, 0, r.stderr)
        upper = report.read_text(encoding="utf-8").upper()
        self.assertTrue("MUST" in upper or "WARN" in upper, "报告应含 MUST/WARN 分级")

    def test_07_eval_fix(self):
        """推荐评估机械检测：产出逐章修改清单。"""
        report = self.tmp / "eval_fix.md"
        r = run_script(SCRIPTS / "eval_fix_check.py", self.src, "--out", report)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(report.exists() and report.stat().st_size > 0, "修改清单未生成")

    def test_08_auto_rewrite(self):
        """L2.5 自动改写层：五类模式被改写，且 AI 味评分不回退。

        自建迷你 docx（含章节标题+五类 AI 味特征），验证 auto_rewrite 真实改写句子，
        并用其自带的 before/after 评分断言自动化没有把 AI 味改重。
        """
        from docx import Document
        mini = self.tmp / "mini_ar.docx"
        out = self.tmp / "mini_ar_out.docx"
        d = Document()
        d.add_heading("第一章 自动改写测试", level=1)
        for t in [
            "他感到愤怒，胸口发闷。",
            "她感到很委屈，眼泪差点掉下来。",
            "他淡淡说道：\"你回来了。\"",
            "他微微一笑道：\"有心了。\"",
            "夜色像一潭死水般沉默。",
            "与此同时，事情有了转机。",
            "另一边，陈雪也在帮忙。",
            "就在这时，门突然开了。",
            "他似乎在犹豫要不要开口。",
        ]:
            d.add_paragraph(t)
        d.save(str(mini))

        r = run_script(SCRIPTS / "auto_rewrite.py", mini, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = doc_text(out)

        # B 情绪直陈 → 行为微描写
        self.assertIn("攥紧了拳", text, "情绪直陈应改写为行为")
        self.assertNotIn("感到愤怒", text, "原情绪直陈应被消除")
        # C 对话标签去烂副词
        self.assertNotIn("淡淡", text, "标签烂副词应被移除")
        self.assertIn("他说：", text, "他淡淡说道 应简化为 他说：")
        # D 陈词比喻替换
        self.assertIn("一片死寂", text, "陈词比喻应被替换")
        # E 套路转场轮换（替换为非待消词，计数应降）
        self.assertNotIn("与此同时", text, "与此同时应被轮换掉")
        self.assertNotIn("另一边", text, "另一边应被轮换掉")
        self.assertIn("同一时刻", text, "与此同时应轮换为 同一时刻")
        # A 扩展填充词
        self.assertNotIn("就在这时", text, "就在这时 应被删除")
        self.assertIn("门突然开了", text, "删除填充词后主干保留")

        # 评分不回退（解析脚本自带 before→after 行）
        m = re.search(r"(\d+)\s*→\s*(\d+)", r.stdout)
        self.assertIsNotNone(m, f"未解析到评分行：{r.stdout}")
        before, after = int(m.group(1)), int(m.group(2))
        self.assertLessEqual(after, before, f"AI 味评分回退：{before}→{after}")

    def test_09_pipeline(self):
        """一键流水线：端到端跑完机械流程，产出汇总报告与全部中间文件。"""
        out = self.tmp / "pipe_out"
        r = run_script(SCRIPTS / "pipeline.py", self.src, "--workdir", out)
        self.assertEqual(r.returncode, 0, r.stderr)

        # 关键中间产物都应生成
        for f in ("draft_map.json", "01_reframed.docx", "02_deai.docx",
                 "04_auto.docx", "99_PIPELINE_SUMMARY.md"):
            self.assertTrue((out / f).exists(), f"流水线未产出 {f}")

        # 汇总报告应点出仍需人工确认/agent 改写的事项
        summ = (out / "99_PIPELINE_SUMMARY.md").read_text(encoding="utf-8")
        self.assertIn("待确认", summ, "汇总报告应列出待确认/agent 改写项")
        self.assertIn("agent 改写", summ, "汇总报告应体现 agent 语义闭环改写")
        self.assertIn("AI 味自动改写评分", summ, "汇总报告应含前后评分")

        # 自动改写版应与原文件不同（确实动了文本）
        self.assertNotEqual(doc_text(self.src), doc_text(out / "04_auto.docx"),
                            "流水线自动改写应产生文本改动")


    def test_10_semantic_scan(self):
        """深层语义扫描：挖出暗示性多角/暧昧候选（WARN-only，不自动改）。"""
        from docx import Document
        mini = self.tmp / "mini_sem.docx"
        out = self.tmp / "sem_report.md"
        d = Document()
        d.add_heading("第一章 语义测试", level=1)
        # A 亲密聚类（同段多 token）+ C 多角强信号 + B 情感边界模糊
        d.add_paragraph("他贴近她，气息拂过耳畔，她的腰微微一颤，两人缠绵至深夜。")
        d.add_paragraph("他脚踏两条船，周旋在几个女人之间，那种暧昧不清的关系连自己都分不清。")
        d.add_paragraph("普通的一段叙述，没有亲密描写，也不涉及多角关系，只是日常对话推进剧情。")
        d.save(str(mini))

        r = run_script(SCRIPTS / "semantic_scan.py", mini, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = out.read_text(encoding="utf-8")
        # 应至少命中 A / B / C 类之一
        self.assertTrue(any(t in rep for t in
                            ["A.亲密暗示聚类", "B.情感边界模糊", "C.多角结构"]),
                        f"语义扫描未报出候选：{rep}")
        # 普通段不应误报（报告不应把"普通的一段叙述"当候选）
        self.assertNotIn("日常对话推进剧情", rep, "普通段落不应被误报为语义风险")

    def test_11_copyright_scan(self):
        """版权扫描：挖出正文疑似侵权引用（明星/IP/歌词，WARN-only）。"""
        from docx import Document
        mini = self.tmp / "mini_cp.docx"
        out = self.tmp / "cp_report.md"
        d = Document()
        d.add_heading("第一章 版权测试", level=1)
        d.add_paragraph("易烊千玺戴着耳机，打开了王者荣耀准备开黑。")
        d.add_paragraph("她轻轻哼起歌词：长亭外古道边，芳草碧连天，晚风拂柳笛声残。")
        d.add_paragraph("主角走进一家普通的小卖部买了瓶水，继续赶路，这一段没有任何侵权内容。")
        d.save(str(mini))

        r = run_script(SCRIPTS / "copyright_scan.py", mini, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = out.read_text(encoding="utf-8")
        self.assertTrue(any(t in rep for t in
                            ["1.真人/明星名", "2.知名IP/作品", "3.歌词/诗文引用"]),
                        f"版权扫描未报出候选：{rep}")
        self.assertNotIn("没有任何侵权内容", rep, "普通段落不应被误报为版权风险")

    def test_12_agent_implicit_signal(self):
        """E 类中置信暗示性软信号：无显式 A/B/C/D token 的"暗示性多角"段应被报为 E 类，且不计入硬候选。"""
        from docx import Document
        mini = self.tmp / "mini_implicit.docx"
        out = self.tmp / "implicit_report.md"
        d = Document()
        d.add_heading("第一章 暗示性测试", level=1)
        # 暗示性留白：深夜(私密空间) + 只对你(情感独占)，无亲密token聚类/边界模糊词/多角词/未成年词
        d.add_paragraph("夜深了，屏退左右，他只对你说：这件事，除了你谁都不能知道。")
        d.add_paragraph("主角走进军帐，与诸将商议明日进军路线，这一段只是正常的权谋推进剧情。")
        d.save(str(mini))

        r = run_script(SCRIPTS / "semantic_scan.py", mini, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = out.read_text(encoding="utf-8")
        # 应报出 E 类中置信暗示性，且不含任何硬候选（A/B/C/D）
        self.assertIn("E.暗示性(中置信-待LLM判定)", rep, f"应报出 E 类暗示性软信号：{rep}")
        self.assertIn("硬候选合计（A/B/C/D）：0", rep, f"E 类不应计入硬候选：{rep}")
        self.assertIn("中置信软信号（E，待 LLM 判定，不计入硬候选）：1", rep, f"E 类计数应为 1：{rep}")
        # 普通权谋段不应误报
        self.assertNotIn("正常的权谋推进剧情", rep, "普通段落不应被误报为语义风险")

    def test_13_cover_check(self):
        """封面核查：自动测尺寸/格式/比例；小图告警；纯色图告警。"""
        from PIL import Image
        try:
            from PIL import Image  # noqa
        except ImportError:
            self.skipTest("未安装 Pillow，跳过封面核查测试")

        def save_img(path, w, h, solid=False):
            img = Image.new("RGB", (w, h), (0, 0, 0))
            if not solid:
                px = img.load()
                for y in range(0, h, 17):
                    for x in range(0, w, 17):
                        px[x, y] = ((x * 7) % 255, (y * 13) % 255, 128)
            img.save(str(path))

        ok_img = self.tmp / "cover_ok.png"
        save_img(ok_img, 900, 1200, solid=False)
        out = self.tmp / "cover_report.md"
        r = run_script(SCRIPTS / "cover_check.py", ok_img, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = out.read_text(encoding="utf-8")
        self.assertIn("像素尺寸", rep, "应给出尺寸检测")
        self.assertIn("✅", rep, "合规图应出现通过标记")
        self.assertNotIn("无法打开图片", rep)

        small = self.tmp / "cover_small.png"
        save_img(small, 300, 400, solid=False)
        out2 = self.tmp / "cover_small.md"
        r2 = run_script(SCRIPTS / "cover_check.py", small, "--out", out2)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("⚠️", out2.read_text(encoding="utf-8"), "小图应告警")

        solid_img = self.tmp / "cover_solid.png"
        save_img(solid_img, 900, 1200, solid=True)
        out3 = self.tmp / "cover_solid.md"
        r3 = run_script(SCRIPTS / "cover_check.py", solid_img, "--out", out3)
        self.assertEqual(r3.returncode, 0, r3.stderr)
        self.assertIn("疑似未设计", out3.read_text(encoding="utf-8"), "纯色图应告警疑似默认模板")

    def test_14_relation_graph(self):
        """人物关系图：含多角关系(男主与两女亲密共现)应标多角预警；普通权谋不误报。"""
        from docx import Document
        mini = self.tmp / "mini_rel.docx"
        out = self.tmp / "rel_report.md"
        d = Document()
        d.add_heading("第一章 多角测试", level=1)
        d.add_paragraph("李雷握住韩梅的手，气息拂过她耳畔，两人相视，情愫暗生。")
        d.add_heading("第二章 多角测试", level=1)
        d.add_paragraph("李雷替王芳拢了拢肩上的披风，指尖擦过她手背，心跳如鼓。")
        d.add_heading("第三章 权谋", level=1)
        d.add_paragraph("李雷走进军帐，与诸将商议进军路线，这是正常的权谋推进。")
        d.save(str(mini))

        r = run_script(SCRIPTS / "relation_graph.py", mini, "--names", "李雷,韩梅,王芳", "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = out.read_text(encoding="utf-8")
        self.assertIn("多角关系高置信预警", rep, f"应标出多角预警：{rep}")
        self.assertIn("李雷", rep, "预警角色应出现")
        self.assertNotIn("诸将", rep, "未命名配角不应进关系图")


    def test_15_wiki_signs_scan(self):
        """维基《AI 写作迹象》识别：各类高/中置信信号被分级报出，正常段落不误报。"""
        from docx import Document
        mini = self.tmp / "mini_wiki.docx"
        out = self.tmp / "wiki_report.md"
        d = Document()
        d.add_heading("第一章 识别测试", level=1)
        # 高置信硬信号
        d.add_paragraph("We should delve into the intricate nuances of the landscape.")  # V 英文词
        d.add_paragraph("这不仅是一幅画，更是一份记录她心理叙事的视觉文献。")  # N 否定平行
        d.add_paragraph("值得注意的是，这种格局的变化值得所有人关注。")  # D 说教免责
        d.add_paragraph("批评者认为，这种方式并不可取，外界也持类似看法。")  # A 模糊归因
        d.add_paragraph("总的来说，尽管面临挑战，但未来仍值得期待。")  # E 僵化结尾
        d.add_paragraph("## 小标题 他**强调**了重点，并 showcase 了承诺。")  # M Markdown残留 + V
        d.add_paragraph("今天天气真好 🚀 我们一起出发吧。")  # J Emoji
        d.add_paragraph("他来了——她走了——风起了——雨落了——夜深了。")  # _ 破折号过量(5)
        # 中置信软信号
        d.add_paragraph("从宇宙大爆炸的奇点到数字营销的最新趋势，跨度极大。")  # R 虚假范围
        d.add_paragraph("主角走进客栈，要了一碗面，坐在角落慢慢吃，窗外街市人来人往，他想起家乡的炊烟。")  # 正常段
        d.save(str(mini))

        r = run_script(SCRIPTS / "wiki_signs_scan.py", mini, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = out.read_text(encoding="utf-8")
        # 高置信硬信号至少应有几类命中
        self.assertTrue(any(t in rep for t in
                            ["V.英文词汇黑名单", "N.否定平行结构", "D.说教式免责声明",
                             "A.模糊归因", "E.僵化结尾", "M.Markdown残留",
                             "J.Emoji异常", "_.破折号过度使用"]),
                        f"维基识别未报出高置信信号：{rep}")
        # 中置信软信号（虚假范围）应单列待人工
        self.assertIn("R.虚假范围", rep, f"应报出中置信虚假范围：{rep}")
        self.assertIn("中置信-待人工", rep, "中置信软信号应标注待人工")
        # 浓度分应出现且 >0
        self.assertIn("AI 味浓度分", rep, "应给出 AI 味浓度分")
        # 正常段落不应被误报（其原文不应出现在报告候选里）
        self.assertNotIn("他想起家乡的炊烟", rep, "正常叙述段不应被误报为 AI 写作迹象")


    def test_16_friendly_error(self):
        """友好报错（R·异常处理）：损坏/非 docx 文件应给中文「原因 + 怎么修」，而非裸 traceback。"""
        bad = self.tmp / "not_a_docx.docx"
        bad.write_bytes(b"this is plainly not a docx zip file")
        out = self.tmp / "should_not_exist.txt"
        r = run_script(SCRIPTS / "extract_docx.py", bad, out)
        self.assertNotEqual(r.returncode, 0, "坏文件应非零退出")
        combined = r.stdout + r.stderr
        self.assertIn("文件不是有效的", combined, "应给出「文件不是有效的 .docx」友好报错")
        self.assertIn("怎么修", combined, "应给出「怎么修」修复建议")

    def test_17_deai_elimination_rate(self):
        """去AI改写效果量化（E·输出准确性）：浓度分应下降并给出消除率，--report 产出报告。"""
        from docx import Document
        mini = self.tmp / "mini_deai.docx"
        out = self.tmp / "mini_deai_out.docx"
        report = self.tmp / "deai_report.md"
        d = Document()
        d.add_heading("第一章 消除率测试", level=1)
        # 这三个词既是 wiki 高置信硬信号（说教免责 / 僵化结尾），
        # 又在 deai_humanizer 的 RULES 删除列表里 → 改写后浓度分应下降
        for t in [
            "值得注意的是，这种格局值得所有人的关注。",
            "综上所述，这件事最终还是定了下来。",
            "毋庸置疑，他的实力确实高出旁人一截。",
        ]:
            d.add_paragraph(t)
        d.save(str(mini))

        r = run_script(SCRIPTS / "deai_humanizer.py", mini, out, "--report", report)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("消除率", r.stdout, f"应输出消除率：{r.stdout}")
        m = re.search(r"AI 味浓度分:\s*(\d+)\s*→\s*(\d+)", r.stdout)
        self.assertIsNotNone(m, f"未解析到浓度分前后值：{r.stdout}")
        before, after = int(m.group(1)), int(m.group(2))
        self.assertLess(after, before, f"机械层改写应降低 AI 味浓度分：{before}→{after}")
        self.assertTrue(report.exists(), "deai_report.md 未生成")
        self.assertIn("消除率", report.read_text(encoding="utf-8"), "报告应含消除率")

    def test_18_eval_readiness(self):
        """推荐评估就绪度自检（E·增值）：小字数书低分、达标健康书高分，并提醒后台自查项。"""
        from docx import Document

        # 中性叙述句：不含钩子/世界观堆砌/AI低质词/说教免责等任何信号，保证"健康书"是真的健康
        NEUTRAL = [
            "清晨的巷口飘着豆浆香，他买了两个包子，边走边吃，顺手把零钱放进口袋。",
            "午后阳光斜照在书页上，他翻了几页，又合上，窗外的蝉声一阵接着一阵。",
            "河边的石阶上有洗衣的妇人，棒槌声此起彼伏，惊起几只水鸟掠过水面。",
            "傍晚的集市渐渐散了，摊主收起布幔，把剩下的菜装进竹筐挑回家去。",
            "他沿着河岸走了一段，看远处灯火一盏盏亮起，又慢慢隐没在雾气里。",
        ]

        def build(path, nch, per_ch):
            d = Document()
            for i in range(1, nch + 1):
                d.add_heading(f"第{i}章 旅程", level=1)
                for j in range(per_ch):
                    d.add_paragraph(NEUTRAL[j % len(NEUTRAL)])
            d.save(str(path))

        def readiness_of(path):
            out = self.tmp / f"rd_{path.stem}.md"
            r = run_script(SCRIPTS / "eval_readiness.py", path, "--out", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            m = re.search(r"综合就绪度:\s*(\d+)/100", r.stdout)
            self.assertIsNotNone(m, f"未解析到就绪度：{r.stdout}")
            return int(m.group(1)), out.read_text(encoding="utf-8")

        # 小字数书：远未达 8 万门槛 → 就绪度应明显偏低
        small = self.tmp / "rd_small.docx"
        build(small, 3, 6)
        small_score, _ = readiness_of(small)
        self.assertLess(small_score, 80, f"小字数书就绪度应偏低，实际 {small_score}")

        # 达标健康书：≥8 万字且章节落在 1500-3000 健康带 → 就绪度应较高
        big = self.tmp / "rd_big.docx"
        build(big, 30, 80)
        big_score, big_rep = readiness_of(big)
        self.assertGreaterEqual(big_score, 80, f"达标健康书就绪度应较高，实际 {big_score}")

        # 报告应含维度评分与「需后台自查」提醒（日更/留存无法从文档判断，不谎报）
        self.assertIn("维度评分", big_rep, "报告应含维度评分")
        self.assertIn("需后台自查", big_rep, "报告应提醒需后台自查项（日更/留存）")
        self.assertIn("综合就绪度", big_rep, "报告应含综合就绪度")

    def test_19_precheck(self):
        """开跑前预检（R·异常处理）：事前校验三类输入，阻塞问题退出码 1 并给「怎么修」。"""
        # 1) 文件不存在 → 阻塞
        r = run_script(SCRIPTS / "precheck.py", self.tmp / "nope.docx")
        self.assertEqual(r.returncode, 1, f"不存在的文件应 exit 1：{r.stdout}")
        self.assertIn("文件不存在", r.stdout, "应指出文件不存在")
        self.assertIn("怎么修", r.stdout, "应给出怎么修")

        # 2) 坏的 .docx（改后缀）→ 阻塞
        bad = self.tmp / "bad_pre.docx"
        bad.write_bytes(b"not a docx at all")
        r2 = run_script(SCRIPTS / "precheck.py", bad)
        self.assertEqual(r2.returncode, 1, f"坏 docx 应 exit 1：{r2.stdout}")
        self.assertIn("不是有效的", r2.stdout, "应指出不是有效的 .docx")
        self.assertIn("怎么修", r2.stdout, "应给出怎么修")

        # 3) 正常 .docx → 通过
        r3 = run_script(SCRIPTS / "precheck.py", self.src)
        self.assertEqual(r3.returncode, 0, f"正常文件应 exit 0：{r3.stdout}{r3.stderr}")
        self.assertIn("预检通过", r3.stdout, "正常文件应报预检通过")

    def test_20_trigger_decision_tree(self):
        """触发决策树与命令速查卡（A·触发方式）：SKILL.md 应提供场景→动作的决策表。"""
        txt = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("30 秒速判", txt, "应提供「30 秒速判」决策树")
        self.assertIn("命令速查卡", txt, "应提供命令速查卡")
        # 决策树应覆盖"不适合"场景（不能只说能做什么）
        self.assertIn("不适合", txt, "决策树应标明不适合场景")


if __name__ == "__main__":
    unittest.main(verbosity=2)
