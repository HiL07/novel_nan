"""训练样本 → 分组 → 训练集 / 验证集划分（不依赖 torch，便于单独测试，远程执行时同样复用）。

样本：
- 任务目录 samples.txt         所有来源按顺序以空行拼接（历史格式，保持不变）
- 任务配置 config.sampleIndex  每个来源在 samples.txt 中的字符区间 [{type, name, fileId?, start, end}]（新任务才有）

分组：每个来源先按章节切分（text_loader.split_chapters），每章为一组；识别不到章节时整个来源为一组。
划分（mode）：
- group     ≥ 2 组：按固定种子打乱后整组选入验证集，直到约 valRatio；同一组不会同时出现在两边
- tail      分组不足或无法按组凑出合理比例：取最长分组末尾约 valRatio 的连续片段（段落边界），只在一处与训练集相邻
- disabled  valRatio = 0
- none      验证集太小（不足一个完整的 maxSeqLen 块）等原因无法评估；reason 记录原因，不产出误导性的 eval loss
"""
import random
import re
from pathlib import Path

from .. import text_loader
from . import train_config


def load_sources(job_dir: Path, index: list[dict] | None) -> list[dict]:
    text = (job_dir / "samples.txt").read_text(encoding="utf-8")
    if not index:  # 旧任务：没有来源边界，整体视为一个来源
        sources = [{"type": "text", "name": "samples.txt", "text": text}]
    else:
        sources = [{**{k: v for k, v in s.items() if k not in ("start", "end")}, "text": text[s["start"]:s["end"]]}
                   for s in index]
    for s in sources:
        s["text"], s["removedLines"] = strip_boilerplate(s["text"])
    return sources


# 电子书版权页（「版权信息」块）：只在该标题之后的少量行内删除这些套话，不碰正文
_COPYRIGHT_HEAD = re.compile(r"^[ \t　]*版[ \t　]*权[ \t　]*信[ \t　]*息[ \t　]*$")
_COPYRIGHT_LINE = re.compile(r"^[ \t　]*(书名|作者|著者|译者|封面设计|责任编辑|出版|出品|ISBN|定价|此书授权|本书由|版权归|版权所有)")
_COPYRIGHT_SCAN = 12


def strip_boilerplate(text: str) -> tuple[str, list[str]]:
    """删除「版权信息」标题及其后 _COPYRIGHT_SCAN 行内的版权套话行。返回 (文本, 被删除的行)。"""
    lines = text.split("\n")
    drop: set[int] = set()
    for i, line in enumerate(lines):
        if not _COPYRIGHT_HEAD.match(line):
            continue
        drop.add(i)
        for j in range(i + 1, min(i + 1 + _COPYRIGHT_SCAN, len(lines))):
            if _COPYRIGHT_LINE.match(lines[j]):
                drop.add(j)
            elif lines[j].strip():
                break
    if not drop:
        return text, []
    return "\n".join(l for i, l in enumerate(lines) if i not in drop), [lines[i].strip() for i in sorted(drop)]


def build_groups(sources: list[dict]) -> list[dict]:
    groups = []
    for si, src in enumerate(sources):
        chapters = [ch for ch in text_loader.split_chapters(src["text"]) if ch["content"].strip()]
        if not chapters and src["text"].strip():  # 只有标题行、没有正文时：整个来源作为一组，不丢文本
            chapters = [{"title": "全文", "content": src["text"]}]
        for ci, ch in enumerate(chapters):
            if ch["content"].strip():
                # 章节标题行也是原文的一部分（与改动前整段训练的内容一致）；「全文 / 序」是切分器补的名字，不加
                real_title = ch["title"] not in ("全文", "序/前言")
                groups.append({"id": f"{si}:{ci}", "source": src.get("name") or src.get("type"), "title": ch["title"],
                               "text": f"{ch['title']}\n{ch['content']}" if real_title else ch["content"]})
    return groups


def split(groups: list[dict], ratio: float, seed: int) -> dict:
    """返回 {mode, train: [group], val: [group], warnings: [], reason}（尚未分词，块数检查见 check_blocks）。"""
    total = sum(len(g["text"]) for g in groups)
    if not groups:
        return {"mode": "none", "train": [], "val": [], "warnings": [], "reason": "没有可用的样本文本"}
    if ratio <= 0:
        return {"mode": "disabled", "train": groups, "val": [], "warnings": [], "reason": "valRatio = 0，未划分验证集"}
    target = total * ratio
    warnings = []
    if len(groups) >= train_config.VAL_MIN_GROUPS:
        order = list(range(len(groups)))
        random.Random(seed).shuffle(order)
        picked, size = [], 0
        for i in order:
            n = len(groups[i]["text"])
            if size + n <= target * train_config.VAL_MAX_OVERSHOOT and len(picked) < len(groups) - 1:
                picked.append(i)
                size += n
            if size >= target:
                break
        if size >= target * 0.5:
            val_ids = set(picked)
            return {"mode": "group", "train": [g for i, g in enumerate(groups) if i not in val_ids],
                    "val": [groups[i] for i in sorted(val_ids)], "warnings": warnings, "reason": None}
        warnings.append(f"按章节/来源分组无法凑出约 {ratio:.0%} 的验证集（各组长度差异过大），改用末尾连续片段")
    else:
        warnings.append(f"只有 {len(groups)} 个章节/来源分组，无法按组划分，改用末尾连续片段（只在一处与训练集相邻）")
    return _tail_split(groups, ratio, warnings)


def _tail_split(groups: list[dict], ratio: float, warnings: list[str]) -> dict:
    """从最长的分组末尾（段落边界）切出约 ratio 的连续片段作为验证集。"""
    k = max(range(len(groups)), key=lambda i: len(groups[i]["text"]))
    src = groups[k]
    text = src["text"]
    want = int(sum(len(g["text"]) for g in groups) * ratio)
    if want >= len(text):
        return {"mode": "none", "train": groups, "val": [], "warnings": warnings,
                "reason": "最长的分组也短于验证集所需长度，无法取连续片段；未做评估"}
    cut = text.rfind("\n", 0, len(text) - want)
    cut = cut if cut > 0 else len(text) - want
    head, tail = text[:cut].rstrip(), text[cut:].strip()
    if not head or not tail:
        return {"mode": "none", "train": groups, "val": [], "warnings": warnings,
                "reason": "文本过短，无法切出验证片段；未做评估"}
    train = groups[:k] + [{**src, "id": src["id"] + ":head", "text": head}] + groups[k + 1:]
    val = [{**src, "id": src["id"] + ":tail", "title": f"{src['title']}（末尾片段）", "text": tail}]
    return {"mode": "tail", "train": train, "val": val, "warnings": warnings, "reason": None}


def join(groups: list[dict]) -> str:
    return "\n\n".join(g["text"] for g in groups)


_PARA_MIN = 20


def paragraph_overlap(train: list[dict], val: list[dict]) -> int:
    """验证集中与训练集完全相同的段落数（≥ 20 字，去空白后比较），用于发现重复文本造成的泄漏。"""
    def paras(groups):
        return {re.sub(r"\s+", "", p) for g in groups for p in g["text"].split("\n") if len(p.strip()) >= _PARA_MIN}

    return len(paras(train) & paras(val))


def report(plan: dict) -> dict:
    """写入 meta.json 的划分摘要（不含正文）。"""
    def side(groups):
        return {"groups": len(groups), "chars": sum(len(g["text"]) for g in groups)}

    train_ids, val_ids = {g["id"] for g in plan["train"]}, {g["id"] for g in plan["val"]}
    return {"mode": plan["mode"], "reason": plan["reason"], "warnings": plan["warnings"],
            "train": side(plan["train"]), "val": side(plan["val"]),
            "valGroups": [{"id": g["id"], "source": g["source"], "title": g["title"], "chars": len(g["text"])}
                          for g in plan["val"]],
            "groupOverlap": len(train_ids & val_ids), "paragraphOverlap": paragraph_overlap(plan["train"], plan["val"])}
