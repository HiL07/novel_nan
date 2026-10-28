"""创作素材：分类与属性模板、提取选项，以及 AI 语义检索（查询扩展 + 重排）。

素材流程分步：提取（只读原文，记实体和事实）→ 整理卡片（material_facts.compile）→ 待确认候选（Java）→ 用户确认后进素材库。
分类代码与 Java MaterialService / 前端 api/material.js 保持一致。
"""
import re

from pydantic import BaseModel, Field

from .llm_client import ModelConfig, chat, parse_json

# 分类：代码 → (名称, 建议的属性字段)。与前端 api/material.js 的 attrs 保持一致
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "world": ("世界观", ["规则内容", "代价", "限制", "谁能打破", "对社会的影响"]),
    "faction": ("势力", ["结构", "目标", "资源", "内部矛盾"]),
    "character": ("角色", ["人设核心", "反差", "能力", "动机", "关系", "名场面"]),
    "monster": ("怪物", ["外形", "能力", "弱点及原因", "习性", "社会结构", "来源", "与人类的关系"]),
    "location": ("地点", ["特征", "危险", "特殊规则", "产出"]),
    "item": ("物品功法", ["作用", "代价", "获取方式", "限制"]),
    "plot": ("情节", ["起因", "冲突", "转折", "结果", "功能"]),
}


class MaterialOptions(BaseModel):
    """提取时是否记录设定实体（只读原文：实体 + 核实过的事实，见 material_facts.scan）、记哪些分类、额外关注点、
    每块读几遍（第二遍带着已知实体补漏）、分块字数（短章节会合并到一块）。整理卡片是之后单独的一步。"""

    enabled: bool = False
    categories: list[str] = Field(default_factory=lambda: list(CATEGORIES))
    focus: str = Field(default="", max_length=300)
    rounds: int = Field(default=2, ge=1, le=2)
    chunkChars: int = Field(default=3000, ge=1500, le=6000)

    def active_categories(self) -> list[str]:
        return [c for c in self.categories if c in CATEGORIES] or list(CATEGORIES)


def _norm_title(t: str) -> str:
    return re.sub(r"[\s·・,，。、:：\"'“”《》（）()]+", "", t or "").lower()


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in re.split(r"[、,，;；/]", str(v or "")) if s.strip()]


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


