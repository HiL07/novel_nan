"""创作素材：提取时的素材候选（提示词片段 + 跨分块合并）与 AI 语义检索（查询扩展 + 重排）。

素材只是「候选」：由 Java 后端存为待确认，用户确认后才进入素材库。
分类代码与 Java MaterialService / 前端 api/material.js 保持一致。
"""
import hashlib
import re

from pydantic import BaseModel, Field

from .llm_client import ModelConfig, chat, parse_json

# 分类：代码 → (名称, 建议的属性字段)
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "world": ("世界观", ["规则", "影响", "适用题材"]),
    "faction": ("势力", ["类型", "立场", "实力", "特点"]),
    "character": ("角色", ["身份", "性格", "能力", "经历"]),
    "monster": ("怪物", ["外形", "能力", "弱点", "栖息地", "习性"]),
    "location": ("地点", ["类型", "特点"]),
    "item": ("物品功法", ["类别", "作用", "代价"]),
    "plot": ("情节", ["套路", "冲突", "转折", "可借鉴之处"]),
}
class MaterialOptions(BaseModel):
    """提取范围：是否提取素材、提取哪些分类、每块最多几条、额外关注点（自由文本）、候选上限。"""

    enabled: bool = False
    categories: list[str] = Field(default_factory=lambda: list(CATEGORIES))
    maxPerChunk: int = Field(default=2, ge=1, le=5)
    focus: str = Field(default="", max_length=300)
    # 合并去重后最多保留几条候选（按出现章节数从多到少）；超出的不进候选箱，任务说明里会写明
    maxCandidates: int = Field(default=500, ge=20, le=3000)

    def active_categories(self) -> list[str]:
        return [c for c in self.categories if c in CATEGORIES] or list(CATEGORIES)


def prompt_fragment(opts: MaterialOptions) -> str:
    cats = opts.active_categories()
    cat_desc = "；".join(f"{c}={CATEGORIES[c][0]}（属性如：{'、'.join(CATEGORIES[c][1])}）" for c in cats)
    focus = f"\n特别关注：{opts.focus.strip()}" if opts.focus.strip() else ""
    return (
        f'另外，在同一个 JSON 中增加字段 "materials"：从本片段提炼最多 {opts.maxPerChunk} 条可在其他小说中借用的创作素材，'
        f"只提炼有独特价值的设定或创意，没有就输出空数组。分类只能是：{cat_desc}。\n"
        '每条格式：{"category":"分类代码","subtype":"细分类型","title":"简短名称","summary":"一句话概括，不超过60字",'
        '"attributes":{"属性名":"值"},"tags":["2~5个标签"],"excerpt":"原文中最能体现它的一句，不超过60字"}。\n'
        f"用自己的话概括，不要大段照抄原文。{focus}"
    )


def _norm_title(t: str) -> str:
    return re.sub(r"[\s·・,，。、:：\"'“”《》（）()]+", "", t or "").lower()


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in re.split(r"[、,，;；/]", str(v or "")) if s.strip()]


def merge_candidates(chunks: list[tuple[str, dict]], opts: MaterialOptions) -> list[dict]:
    """chunks: [(章节标题, 分块解析结果)]。同分类、标题相近的候选合并（属性取并集，记录出现的章节）。
    返回全部合并结果（出现章节多的在前），截断到 maxCandidates 由调用方做，以便告诉用户共识别了多少条。"""
    allowed = set(opts.active_categories())
    merged: dict[tuple[str, str], dict] = {}
    for chapter_title, result in chunks:
        for m in result.get("materials") or []:
            if not isinstance(m, dict):
                continue
            cat, title = str(m.get("category", "")).strip(), str(m.get("title", "")).strip()[:100]
            if cat not in allowed or not title:
                continue
            key = (cat, _norm_title(title))
            attrs = m.get("attributes") if isinstance(m.get("attributes"), dict) else {}
            cur = merged.get(key)
            if cur is None:
                cur = merged[key] = {
                    "candidateId": hashlib.sha1(f"{cat}:{key[1]}".encode()).hexdigest()[:12],
                    "category": cat, "subtype": str(m.get("subtype") or "")[:32], "title": title,
                    "summary": str(m.get("summary") or "")[:300], "attributes": {}, "tags": [],
                    "excerpt": str(m.get("excerpt") or "")[:200], "chapters": [],
                }
            for k, v in attrs.items():
                k = str(k).strip()[:20]
                if not k or v in (None, "", []):
                    continue
                if k not in cur["attributes"]:
                    cur["attributes"][k] = v
                elif isinstance(cur["attributes"][k], list) or isinstance(v, list):
                    vals = _as_list(cur["attributes"][k]) + [x for x in _as_list(v) if x not in _as_list(cur["attributes"][k])]
                    cur["attributes"][k] = vals[:10]
            for t in _as_list(m.get("tags")):
                if t not in cur["tags"] and len(cur["tags"]) < 8:
                    cur["tags"].append(t[:20])
            if len(str(m.get("summary") or "")) > len(cur["summary"]):
                cur["summary"] = str(m["summary"])[:300]
            if chapter_title not in cur["chapters"]:
                cur["chapters"].append(chapter_title)
    # 出现章节越多越可能是核心设定，排在前面
    return sorted(merged.values(), key=lambda c: -len(c["chapters"]))


# ---------------------------------------------------------------- AI 语义检索

class ExpandRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    model: ModelConfig


class RerankItem(BaseModel):
    id: int
    category: str = ""
    title: str = ""
    summary: str = ""
    tags: list[str] = []


class RerankRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    items: list[RerankItem] = Field(max_length=300)
    limit: int = Field(default=20, ge=1, le=50)
    model: ModelConfig


def expand_query(req: ExpandRequest) -> dict:
    """把自然语言需求扩展成关键词 / 标签 / 分类，供数据库初筛。"""
    cats = "、".join(f"{c}={v[0]}" for c, v in CATEGORIES.items())
    text = chat(req.model, [
        {"role": "system", "content": "你是小说创作素材库的检索助手，只输出 JSON。"},
        {"role": "user", "content": (
            f"用户想查找：{req.query}\n分类代码：{cats}\n"
            '输出 {"keywords":["3~8个可能出现在素材标题或摘要里的同义词、相关词"],'
            '"tags":["可能的标签"],"categories":["最相关的分类代码，不确定就留空数组"]}')},
    ], max_tokens=300, retries=1)
    data = parse_json(text)
    return {"keywords": _as_list(data.get("keywords"))[:8], "tags": _as_list(data.get("tags"))[:8],
            "categories": [c for c in _as_list(data.get("categories")) if c in CATEGORIES]}


def rerank(req: RerankRequest) -> list[dict]:
    """让模型按需求对候选素材打分，返回 [{id, score, reason}]（只含相关的）。"""
    if not req.items:
        return []
    lines = "\n".join(
        f"{it.id}|{CATEGORIES.get(it.category, (it.category,))[0]}|{it.title}|{it.summary[:80]}|{'、'.join(it.tags[:5])}"
        for it in req.items)
    text = chat(req.model, [
        {"role": "system", "content": "你是小说创作素材库的检索助手，只输出 JSON。"},
        {"role": "user", "content": (
            f"用户需求：{req.query}\n候选素材（id|分类|标题|摘要|标签）：\n{lines}\n\n"
            f"挑出与需求最相关的最多 {req.limit} 条，按相关度从高到低输出 "
            '{"results":[{"id":数字,"score":0到100,"reason":"不超过30字的匹配理由"}]}，不相关的不要输出。')},
    ], max_tokens=1200, retries=1)
    ids = {it.id for it in req.items}
    out = []
    for r in parse_json(text).get("results") or []:
        try:
            rid = int(r.get("id"))
        except (TypeError, ValueError):
            continue
        if rid in ids:
            out.append({"id": rid, "score": max(0, min(100, int(r.get("score") or 0))),
                        "reason": str(r.get("reason") or "")[:60]})
    return out[: req.limit]


