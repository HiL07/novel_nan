"""素材量级标注：每条素材在原书里的影响范围 1–5（跨书通用，不用各书自己的境界名）。

灵感墙 / AI 构思按故事进度过滤素材时用（开篇不该全是神明）。一次调用标 BATCH 条，模型 = 大模型或 GGUF；
代码只收 1–5 的整数、id 必须是本批里的，其他丢掉。Java 负责保存，作者手改过的（tierBy = user）Java 不会送来。
"""
from . import llm_client, local_extract

BATCH = 20

TIERS = {
    1: "个人 / 街头：一个人、一伙山匪、一头野兽、一件随身物品，影响几个人",
    2: "地方：村镇、小门派、一片山林的妖王，影响一地",
    3: "一国 / 大宗门：王朝、大宗门、一方霸主，影响一国",
    4: "大陆 / 天下：魔族大军、天下第一宗、灭世级灾兽，影响整个大陆",
    5: "神明 / 世界之外：神、天道、上古存在、世界规则本身",
}

SYSTEM = "你是网络小说的设定编辑，给素材标「量级」。只输出 JSON，不要任何多余文字。"


def tier_scale() -> str:
    return "\n".join(f"{k} = {v}" for k, v in TIERS.items())


def _item_text(n: int, m: dict) -> str:
    attrs = m.get("attributes") if isinstance(m.get("attributes"), dict) else {}
    attr = "；".join(f"{k}：{'、'.join(map(str, v)) if isinstance(v, list) else v}" for k, v in attrs.items() if v)[:200]
    body = "；".join(x for x in [str(m.get("summary") or "")[:150], str(m.get("detail") or "")[:150], attr] if x)
    return f"{n}. [{m.get('category') or ''}] {m.get('title') or ''}：{body}"


def label(items: list[dict], cfg: llm_client.ModelConfig) -> dict:
    """items: [{id, category, title, summary, detail, attributes}] → {tiers: {id: {tier, reason}}, skipped, usage, model}"""
    items = items[:BATCH]
    usage = llm_client.new_usage(cfg)
    lines = "\n".join(_item_text(i, m) for i, m in enumerate(items, 1))
    prompt = (f"量级按影响范围（这东西在原书里能影响多大范围、有多强）：\n{tier_scale()}\n\n"
              "规则：物品 / 功法按使用者能达到的影响范围算；地点按在那里发生的事的规模算；"
              "情节按冲突波及的范围算；拿不准时取更低的一级。\n\n"
              f"【素材】\n{lines}\n\n"
              '输出：{"items":[{"n":序号,"tier":1到5的整数,"reason":"20 字内的理由"}]}，每条素材都要有。')
    text = llm_client.chat(cfg, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                           max_tokens=60 * len(items) + 200, usage=usage)
    data = local_extract.parse_lenient(text)
    out = {}
    for r in data.get("items") or []:
        if not isinstance(r, dict):
            continue
        try:
            n, tier = int(r.get("n")), int(r.get("tier"))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= len(items) and 1 <= tier <= 5:
            out[str(items[n - 1]["id"])] = {"tier": tier, "reason": str(r.get("reason") or "").strip()[:30]}
    return {"tiers": out, "skipped": len(items) - len(out), "usage": usage, "model": cfg.model}
