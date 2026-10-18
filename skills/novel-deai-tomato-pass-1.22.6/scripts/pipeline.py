# -*- coding: utf-8 -*-
"""pipeline.py — 去 AI 味 + 过审 一键流水线（机械流程自动驾驶）

把原先要一条条手敲的 7 个步骤串成一条命令，跑完机械能自动做的一切，
并产出一份汇总报告，明确告诉用户「哪些已自动搞定、哪些仍需人工确认」。

设计原则：
- 机械可枚举的部分（提取/映射草稿/重构/去AI/L2诊断/L2.5自动改写/L2复评/评估检测）
  全自动跑完；需要人拍板的部分（映射候选定稿、书名、L3 精修、封面版权）只「报告」不「代做」。
- 每步独立 try/except，单步失败不阻断后续；汇总报告标注每步状态。
- 复用同解释器（venv python）调用兄弟脚本，无需任何硬编码路径。

用法:
  python pipeline.py <源文件.docx> [--workdir DIR] [--no-reframe] [--no-eval] [--max-pass N]
                       [--names 甲,乙] [--cover <封面图路径>] [--quick]

产出（默认在 源文件同目录/<源文件名>_tomato_out/）:
  novel_text.txt        提取文本
  00_wizard.md          映射向导扫描报告
  draft_map.json        映射草稿（待用户定稿 candidates / title_new）
  01_reframed.docx      重构后（硬伤修复）
  02_deai.docx          L1 去 AI 机械层
  03_deep_before.md     L2 诊断（改写前）
  04_auto.docx          L2.5 自动改写后
  05_deep_after.md      L2 诊断（改写后，评分应下降）
  06_eval.md            8万字评估机械检测清单
  07_semantic.md        深层语义风险扫描（WARN-only 候选，交 L3/agent 判定）
  08_copyright.md       文本级版权风险扫描（WARN-only 候选，交人工核查）
  09_relation.md        人物亲密关系图（自动标多角预警，交 agent 定向改写）
  10_cover.md           封面客观指标自动核查（仅 --cover 时生成）
  11_wiki_signs.md      维基《AI 写作迹象》识别扫描（高/中置信分级，交 L3/agent 定向精修）
  deai_report.md        去AI机械层改写效果量化（AI 味浓度分 前→后 + 消除率 + 残留信号）
  12_eval_readiness.md  推荐评估就绪度自检（0-100 综合分 + 维度雷达 + 短板清单）
  99_PIPELINE_SUMMARY.md 汇总：文件清单 + 前后评分 + 消除率 + 就绪度 + 待人工确认/待 agent 改写项

--quick 模式（没耐心版）：
  在以上基础上把"待人工确认项"精简为**仅剩不可自动化**的极短清单（封面图确认 / 核心情节决策），
  其余机械与高置信改写项自动标注"已搞定"，产出单份精简汇总，减少用户阅读量。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from errkit import hint_from_stderr, safe_main
from precheck import check as precheck_file


def sibling(name):
    return str(Path(__file__).resolve().parent / name)


def run_step(log, name, *args, must=False):
    """跑一个兄弟脚本，记录到 log；must=True 时失败抛异常。"""
    cmd = [sys.executable, sibling(args[0]), *map(str, args[1:])]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent))
        ok = r.returncode == 0
        log.append((name, ok, r.stdout.strip()[-600:], r.stderr.strip()[-400:]))
        if must and not ok:
            raise RuntimeError(f"步骤失败 [{name}]:\n{r.stderr}")
        return r
    except Exception as e:  # noqa
        log.append((name, False, "", str(e)[:400]))
        if must:
            raise
        return None


def parse_score(stdout):
    """从 deai_deep_report 的 'MUST: x | WARN: y' 解析 MUST+WARN 合计。"""
    m = re.search(r"MUST:\s*(\d+)\D*WARN:\s*(\d+)", stdout or "")
    if m:
        return int(m.group(1)) + int(m.group(2))
    return None


def parse_elimination(stdout):
    """从 deai_humanizer 的 '消除率 N%' 解析消除率（整数百分比）。"""
    m = re.search(r"消除率\s*(\d+)%", stdout or "")
    return int(m.group(1)) if m else None


def parse_readiness(stdout):
    """从 eval_readiness 的 '综合就绪度: N/100' 解析就绪度分。"""
    m = re.search(r"综合就绪度:\s*(\d+)/100", stdout or "")
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser(description="去AI味+过审 一键流水线")
    ap.add_argument("src", help="源 .docx")
    ap.add_argument("--workdir", help="输出目录（默认 <源文件>_tomato_out）")
    ap.add_argument("--no-reframe", action="store_true", help="跳过关系重构（只做去AI流水线）")
    ap.add_argument("--no-eval", action="store_true", help="跳过 8万字评估检测")
    ap.add_argument("--max-pass", type=int, default=2, help="传给 auto_rewrite 的迭代轮数")
    ap.add_argument("--names", help="人物关系图角色名（逗号分隔），如 甲,乙,丙")
    ap.add_argument("--cover", help="封面图片路径；给定则自动跑 cover_check.py 出 10_cover.md")
    ap.add_argument("--quick", action="store_true",
                    help="精简模式：汇总仅列不可自动化项（封面图确认/核心情节决策），其余标'已搞定'")
    args = ap.parse_args()

    src = Path(args.src).resolve()
    if not src.exists():
        raise ValueError(
            f"源文件不存在：{src}（检查路径是否拼写正确、是否用了绝对路径；"
            f"把文件拖进终端时记得给路径加引号）"
        )

    # 0) 开跑前预检（事前校验：路径/格式/有效性/占用/依赖，避免跑一半才抛原生异常）
    blockers, warns = precheck_file(src)
    if blockers:
        print("=" * 56)
        print("❌ 开跑前预检未通过，流水线已终止（未改动任何文件）")
        print("=" * 56)
        for i, (t, c, f) in enumerate(blockers, 1):
            print(f"{i}. ⚠️ {t}")
            print(f"   原因：{c}")
            print(f"   怎么修：{f}")
        print("\n按上面修好后重新运行本命令即可。也可单独跑 "
              "`python scripts/precheck.py <书.docx>` 只做体检。")
        sys.exit(1)
    for t, c, f in warns:
        print(f"⚠️ {t}：{c}（怎么修：{f}）")

    workdir = Path(args.workdir).resolve() if args.workdir else \
        src.parent / f"{src.stem}_tomato_out"
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"工作目录: {workdir}")

    log = []
    summary = {"src": str(src), "workdir": str(workdir), "steps": []}

    # 1) 提取
    txt = workdir / "novel_text.txt"
    run_step(log, "extract", "extract_docx.py", src, txt)

    # 2) 映射向导（自动产出草稿，待用户定稿）
    draft = workdir / "draft_map.json"
    wizard_md = workdir / "00_wizard.md"
    run_step(log, "wizard", "build_map_wizard.py", src, "--map", draft, "--out", wizard_md)

    title_new = ""
    candidates_count = 0
    chapter_swap_count = 0
    try:
        dm = json.loads(draft.read_text(encoding="utf-8"))
        title_new = dm.get("title_new", "") or ""
        candidates_count = len(dm.get("candidates", []))
        chapter_swap_count = len(dm.get("chapter_swaps", {}))
    except Exception:
        pass

    # 3) 关系重构（用草稿 map；书名待用户拍板时跳过 title 改写以免误改）
    reframed = workdir / "01_reframed.docx"
    if not args.no_reframe:
        reframe_args = ["reframe_novel.py", src, reframed, "--map", draft]
        if title_new:
            reframe_args += ["--title-new", title_new]
        run_step(log, "reframe", *reframe_args)
    deai_in = reframed if (reframed.exists() and not args.no_reframe) else src

    # 4) L1 去 AI 机械层（--report 产出消除率量化报告）
    deai = workdir / "02_deai.docx"
    r_deai = run_step(log, "L1_humanizer", "deai_humanizer.py", deai_in, deai,
                      "--report", workdir / "deai_report.md")

    # 5) L2 诊断（改写前）
    deep_before = workdir / "03_deep_before.md"
    rb = run_step(log, "L2_deep_before", "deai_deep_report.py", deai, "--out", deep_before)

    # 6) L2.5 自动改写（迭代到规则极限）
    auto = workdir / "04_auto.docx"
    run_step(log, "L2.5_auto_rewrite", "auto_rewrite.py", deai, auto, "--max-pass", args.max_pass)

    # 7) L2 诊断（改写后，评分应下降）
    deep_after = workdir / "05_deep_after.md"
    ra = run_step(log, "L2_deep_after", "deai_deep_report.py", auto, "--out", deep_after)

    # 8) 8万字评估机械检测
    eval_md = workdir / "06_eval.md"
    if not args.no_eval:
        run_step(log, "eval_fix", "eval_fix_check.py", auto, "--out", eval_md)

    # 8.5) 推荐评估就绪度自检（宏观总览，对齐 8 万字硬性门槛）
    readiness_md = workdir / "12_eval_readiness.md"
    r_readiness = None
    if not args.no_eval:
        r_readiness = run_step(log, "eval_readiness", "eval_readiness.py", auto,
                               "--out", readiness_md)

    # 9) 深层语义风险扫描（WARN-only 辅助，不自动改，交 L3 判定）
    semantic_md = workdir / "07_semantic.md"
    run_step(log, "semantic_scan", "semantic_scan.py", auto, "--out", semantic_md)

    # 10) 文本级版权风险扫描（WARN-only 辅助，交人工核查）
    copyright_md = workdir / "08_copyright.md"
    run_step(log, "copyright_scan", "copyright_scan.py", auto, "--out", copyright_md)

    # 11) 人物亲密关系图（自动标多角预警，交 agent 定向改写，不改字）
    relation_md = workdir / "09_relation.md"
    rel_args = ["relation_graph.py", auto, "--out", relation_md]
    if args.names:
        rel_args += ["--names", args.names]
    run_step(log, "relation_graph", *rel_args)

    # 12) 封面客观指标自动核查（仅给定 --cover 时）
    cover_md = workdir / "10_cover.md"
    if args.cover:
        cover_path = Path(args.cover).resolve()
        run_step(log, "cover_check", "cover_check.py", cover_path, "--out", cover_md)

    # 13) 维基《AI 写作迹象》识别扫描（高/中置信分级，WARN-only 交 L3/agent 精修）
    wiki_md = workdir / "11_wiki_signs.md"
    run_step(log, "wiki_signs_scan", "wiki_signs_scan.py", auto, "--out", wiki_md)

    # ---- 汇总 ----
    before_total = parse_score(rb.stdout if rb else "")
    after_total = parse_score(ra.stdout if ra else "")
    score_line = " unavailable（诊断脚本未产出评分）"
    if before_total is not None and after_total is not None:
        delta = after_total - before_total
        score_line = (f" {before_total} → {after_total} "
                      f"({'减少' if delta < 0 else '增加' if delta > 0 else '持平'} {abs(delta)})")

    # 去AI机械层消除率（来自 deai_humanizer 的 --report 输出）
    deai_rate = parse_elimination(r_deai.stdout if r_deai else "")
    # 推荐评估就绪度（来自 eval_readiness）
    readiness = parse_readiness(r_readiness.stdout if r_readiness else "")

    # 关系图多角预警数（从 stderr 的 [summary] 解析）
    rel_flag = None
    if "relation_graph" in [n for n, _, _, _ in log]:
        for n, ok, out, err in log:
            if n == "relation_graph":
                m = re.search(r"多角预警=(\d+)", err or "")
                if m:
                    rel_flag = int(m.group(1))
                break

    needs_human = []
    if candidates_count:
        needs_human.append(f"映射草稿有 {candidates_count} 条触发词候选待你定稿替换词"
                           f"（见 {draft.name}，把 candidates 定稿后挪入 bulk 再跑 reframe）")
    if not title_new:
        needs_human.append("书名待你拍板（向导留空），定稿后补 --title-new 重跑 reframe")
    if chapter_swap_count:
        needs_human.append(f"有 {chapter_swap_count} 章被标为整章违规候选，需你按 reframe_map.md 写 chapter_swaps")
    needs_human.append("L2.5 未覆盖的章（跨角色声纹趋同 / 段落同构 / 章尾套路）按 llm_rewrite_sop.md 做 L3 精修")
    needs_human.append("深层语义（07_semantic.md 候选 + 09_relation.md 多角预警）："
                       "由 agent 按 agent_semantic_rewrite.md 闭环亲自判断+改写写回 docx，用户抽查"
                       + (f"（已自动标出 {rel_flag} 个多角预警角色）" if rel_flag else ""))
    needs_human.append("文本版权（08_copyright.md 候选）需人工核查授权；封面图/跨库比对仍须人确认"
                       + ("（已自动查封面客观指标见 10_cover.md，仅剩真人肖像/第三方IP/敏感地标 3 项待你点一下）"
                          if args.cover else "（封面客观指标可用 cover_check.py 自动查）"))
    needs_human.append("维基《AI 写作迹象》识别（11_wiki_signs.md）：高置信信号（英文词/否定平行/说教免责/"
                       "模糊归因/僵化结尾/Markdown残留/Emoji/破折号过量）按 humanizer 规则直接改；"
                       "中置信信号（虚假范围/三段式排比/伪造来源）由 agent 读上下文二次判定，勿误杀正常写法")

    # --quick：把可自动化的项从"待办"移到"已搞定"，只留真正不可自动化的
    if args.quick:
        auto_done = [
            f"AI 味自动改写评分{score_line}（L2.5 已消大部分机械型 AI 味）",
            f"深层语义候选已挖出（07/{'09_relation.md' if (workdir/'09_relation.md').exists() else ''}），"
            f"agent 可直接据此闭环改写，无需你通读梳理",
            "正文文本版权已自动扫描（08_copyright.md）",
            "封面客观指标已自动核查（10_cover.md）" if args.cover else "封面客观指标可一键自动查（给 --cover）",
        ]
        irreducible = [
            "📌 封面图内容 3 项点一下：真人肖像 / 第三方IP / 政治敏感地标（脚本看不见图）",
            "📌 核心情节决策：是否删整条感情线 / 改核心人设 / 动你明确要保留的「多角爽点」（涉及大改时 agent 会先问）",
            "📌 抽查：agent 改写处 + 听感（读对话能否分出谁在说话）",
        ]
        needs_human = auto_done + irreducible

    summary_md = ["# 流水线汇总报告", "", f"- 源文件: `{src.name}`", f"- 工作目录: `{workdir}`", ""]
    summary_md.append("## 评分（L2 九项 MUST+WARN 合计，改写前后）")
    summary_md.append(f"- AI 味自动改写评分:{score_line}")
    if deai_rate is not None:
        summary_md.append(f"- 去AI机械层消除率: **{deai_rate}%**（改写前→后 AI 味浓度分下降，详见 deai_report.md）")
    summary_md.append("")
    if readiness is not None:
        summary_md.append("## 推荐评估就绪度（对齐 8 万字硬性门槛）")
        summary_md.append(f"- 综合就绪度: **{readiness}/100**（各维度得分与短板清单见 12_eval_readiness.md）")
        summary_md.append("")
    summary_md.append("## 产出文件")
    for f in ["novel_text.txt", "00_wizard.md", "draft_map.json", "01_reframed.docx",
              "02_deai.docx", "03_deep_before.md", "04_auto.docx", "05_deep_after.md",
              "06_eval.md", "07_semantic.md", "08_copyright.md", "09_relation.md",
              "10_cover.md", "11_wiki_signs.md", "deai_report.md", "12_eval_readiness.md"]:
        p = workdir / f
        mark = "✅" if p.exists() else "⚠️ 未生成"
        summary_md.append(f"- `{f}` {mark}")
    summary_md.append("")
    # ---- 执行中遇到的问题（友好报错，对应 R·异常处理）----
    failed = [(n, ok, err) for (n, ok, _, err) in log if not ok]
    if failed:
        summary_md.append("## ⚠️ 执行中遇到的问题")
        summary_md.append("")
        summary_md.append("以下步骤未正常完成，已给出原因与处理建议；其余步骤不受影响，产出的文件仍可正常使用：")
        summary_md.append("")
        for n, _, err in failed:
            summary_md.append(f"- **{n}**：{hint_from_stderr(err)}")
        summary_md.append("")
    else:
        summary_md.append("## ✅ 全部步骤正常完成")
        summary_md.append("")
    header = "## 待确认 / 待 agent 改写项" if not args.quick else "## 精简待办（quick 模式：仅列不可自动化项）"
    summary_md.append(header)
    for i, h in enumerate(needs_human, 1):
        summary_md.append(f"{i}. {h}")
    summary_md.append("")
    if args.quick:
        summary_md.append("> 快速模式：可自动化的项（AI 味改写 / 语义候选挖掘 / 关系图 / 文本版权 / 封面客观指标）"
                         "已标为「已搞定」，上面只留**真正需你拍板**的 3 类。")
    else:
        summary_md.append("> 本流水线只自动化「可枚举的机械工作」。语义层多女信号、人物关系连贯、"
                         "剧情删改、听感、封面版权仍须人工/agent——详见 manual_fix_sop.md / llm_rewrite_sop.md。")

    (workdir / "99_PIPELINE_SUMMARY.md").write_text("\n".join(summary_md), encoding="utf-8")

    # 控制台摘要
    print("=" * 56)
    print("流水线执行完毕")
    print("=" * 56)
    for name, ok, _, _ in log:
        print(f"  [{'OK' if ok else 'X '}] {name}")
    print("-" * 56)
    print(f"AI 味自动改写评分:{score_line}")
    if deai_rate is not None:
        print(f"去AI机械层消除率: {deai_rate}%")
    if readiness is not None:
        print(f"推荐评估就绪度: {readiness}/100")
    print(f"待人工确认项: {len(needs_human)} 条（见 99_PIPELINE_SUMMARY.md）")
    print(f"汇总报告: {workdir / '99_PIPELINE_SUMMARY.md'}")


if __name__ == "__main__":
    safe_main(main)
