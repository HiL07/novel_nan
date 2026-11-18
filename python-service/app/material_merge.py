"""素材精炼 / 合并（素材流程第 ③ 步，在素材库上做，结果由用户逐条确认）。

1. ``find_groups``（本地向量模型，不花 token）：同一分类里互相很像的素材聚成候选组 —— 跨书的「狼人」，
   或同一本书里几乎重复的「银器防御规则 / 银器伤害规则」。分数 = 内容向量相似度，名称很像时和名称向量相似度取平均
   （不同小说写同一种东西，内容差别大、名称几乎一样），名称相同 / 包含再加分。按分数从高到低贪心合并，
   组大小有上限，并要求新加入的素材和组里每一条都足够像（防止 A 像 B、B 像 C 串成一大串）。
2. ``draft``（大模型 / GGUF，一组一次调用）：判断组里哪些应归到同一个主条目（同一种东西，或同名但写法不同），
   主条目只写共性，每条原来的写法保留为一个「可选版本」（版本名 + 独有设定）。属性值、详细描述的句子、
   版本的独有设定都要在原文里有依据（字符二元组重合），否则丢掉。只是草稿，用户可改，确认后 Java 才真正合并。
"""
import re
import time

from . import llm_client, local_extract
from .local import embedding as local_embedding
from .materials import CATEGORIES, _norm_title

MAX_GROUPS = 500
TITLE_SIM = 0.85     # 名称向量相似度到这个值，算「名称很像」
TITLE_BONUS = 0.08   # 名称相同 / 互相包含时再加的分
CHAIN_SLACK = 0.08   # 新成员和组内每一条的分数至少 = 门槛 - 这个值
MEMBER_TEXT = 500    # 写进提示词的单条素材上限
GROUNDED = 0.4       # 属性值的字符二元组至少这么多比例出现在成员原文里，否则视为模型编的，丢掉


def pair_scores(content, title, names: list[str]):
    """两两的合并分数：内容相似度为主；名称很像（名称向量 ≥ TITLE_SIM）时取 (内容 + 名称) / 2 和内容的较大者 ——
    不同小说写同一种东西（两本书的「狼人」）内容差别大、名称几乎一样；名称相同 / 互相包含再加 TITLE_BONUS。"""
    import numpy as np

    score = np.where(title >= TITLE_SIM, np.maximum(content, (content + title) / 2), content)
    n = len(names)
    for a in range(n):
        for b in range(a + 1, n):
            ta, tb = names[a], names[b]
            if len(ta) >= 2 and len(tb) >= 2 and (ta == tb or ta in tb or tb in ta):
                score[a, b] += TITLE_BONUS
                score[b, a] += TITLE_BONUS
    return score


def find_groups(model_id: str | None, items: list[dict], threshold: float, max_group: int) -> dict:
    """items: [{id, category, title, text}] → {groups: [{ids, score, minScore}], model, modelId, device, encoded, ms}"""
    import numpy as np

    t0 = time.time()
    if not items:
        return {"groups": [], "ms": 0}
    mat, info = local_embedding.vectors(model_id, [it.get("text") or it.get("title") or "" for it in items])
    tmat, _ = local_embedding.vectors(model_id, [it.get("title") or "" for it in items])
    groups = []
    by_cat: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        by_cat.setdefault(it.get("category") or "", []).append(i)
    for idx in by_cat.values():
        if len(idx) < 2:
            continue
        sim = pair_scores(mat[idx] @ mat[idx].T, tmat[idx] @ tmat[idx].T,
                          [_norm_title(items[i].get("title") or "") for i in idx])
        n = len(idx)
        pairs = []
        for a in range(n):
            for b in np.nonzero(sim[a, a + 1:] >= threshold)[0] + a + 1:
                pairs.append((float(sim[a, b]), a, int(b)))
        pairs.sort(reverse=True)
        cluster = list(range(n))
        members = {k: [k] for k in range(n)}
        for _, a, b in pairs:
            ca, cb = cluster[a], cluster[b]
            if ca == cb or len(members[ca]) + len(members[cb]) > max_group:
                continue
            # 新成员和组里每一条都要足够像，防止 A 像 B、B 像 C 串成一大串
            if float(sim[np.ix_(members[ca], members[cb])].min()) < threshold - CHAIN_SLACK:
                continue
            for k in members[cb]:
                cluster[k] = ca
            members[ca].extend(members.pop(cb))
        for ks in members.values():
            if len(ks) < 2:
                continue
            block = sim[np.ix_(ks, ks)]
            off = np.minimum(block[~np.eye(len(ks), dtype=bool)], 1.0)
            groups.append({"ids": [items[idx[k]]["id"] for k in ks], "score": round(float(off.mean()), 4),
                           "minScore": round(float(off.min()), 4)})
    groups.sort(key=lambda g: -g["score"])
    return {"groups": groups[:MAX_GROUPS], "total": len(groups), "ms": int((time.time() - t0) * 1000), **info}


SYSTEM = "你是小说创作素材库的整理助手，只输出 JSON，不要任何多余文字。"


def _member_text(n: int, m: dict) -> str:
    parts = [m.get("summary") or ""]
    attrs = m.get("attributes") or {}
    if attrs:
        parts.append("；".join(f"{k}：{'、'.join(map(str, v)) if isinstance(v, list) else v}" for k, v in attrs.items()))
    if m.get("detail"):
        parts.append(str(m["detail"]))
    body = "；".join(p for p in parts if p)[:MEMBER_TEXT]
    book = f"《{m['book']}》" if m.get("book") else "（手动添加）"
    sub = f"（{m['subtype']}）" if m.get("subtype") else ""
    return f"[{n}] {book} {m.get('title', '')}{sub}：{body}"


def draft_prompt(category: str, members: list[dict]) -> str:
    label, attrs = CATEGORIES.get(category, (category, []))
    lines = "\n".join(_member_text(i + 1, m) for i, m in enumerate(members))
    return (f"下面是素材库里名称或内容相近的 {len(members)} 条「{label}」素材（方括号里是编号）：\n{lines}\n\n"
            "要把它们合并成一个主条目：共性写在主条目里，每条原来的写法保留为一个「可选版本」。"
            "同名但设定不同的（比如一本书里是宗教圣物、另一本里是让人狂信的药剂）也可以合并，作为不同版本。\n"
            "任务：\n"
            "1. same：哪些编号应该归到这个主条目（同一种东西，或同名 / 同用途但写法不同）。"
            "毫不相干的不要放进来；只剩一条时给空数组。\n"
            "2. 主条目：title 用通用的名称；summary 一句话（不超过 80 字），各版本差别大时写成"
            "「X：有 N 种写法——①版本名：…；②版本名：…」；detail 只写它们共有的设定（可以很短，没有共性就留空）；"
            f"attributes 按这些属性写共性（没有共性的属性省略）：{'、'.join(attrs)}；tags 3~6 个。\n"
            "3. variants：same 里每个编号一个版本：label 是版本名（不超过 8 个字，概括这一版是什么，如「宗教圣物」「狂信药剂」）；"
            "note 是这一版独有的具体设定（不超过 80 字，如「饮者丧失自我、成为狂信徒」），不要写「强调」「突出」这类评价。\n"
            "只依据给出的内容，不编造；原文没提到的属性不写。\n"
            '输出：{"same":[编号],"title":"","subtype":"","summary":"","detail":"","attributes":{},"tags":[],'
            '"variants":{"编号":{"label":"版本名","note":"独有设定"}}}')


def _text(v, limit: int) -> str:
    if isinstance(v, list):
        v = "、".join(map(str, v))
    return str(v or "").strip()[:limit]


def draft(category: str, members: list[dict], cfg: llm_client.ModelConfig) -> dict:
    """members: [{id, book, title, subtype, summary, attributes, detail}] → 合并稿
    {same: [id], title, subtype, summary, detail, attributes, tags, variants: {id: {label, note}}, droppedAttributes, usage}"""
    usage = llm_client.new_usage(cfg)
    text = llm_client.chat(cfg, [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": draft_prompt(category, members)}],
                           max_tokens=1500, usage=usage)
    data = local_extract.parse_lenient(text)
    ids = [m["id"] for m in members]

    def to_id(v):
        try:
            n = int(re.sub(r"\D", "", str(v)) or 0)
        except ValueError:
            return None
        return ids[n - 1] if 1 <= n <= len(ids) else None

    same = [i for i in dict.fromkeys(to_id(v) for v in data.get("same") or []) if i is not None]
    by_id = {m["id"]: m for m in members}
    variants = {}
    raw = data.get("variants") if isinstance(data.get("variants"), dict) else {}
    for k, v in raw.items():
        i = to_id(k)
        if i is None or i not in same:
            continue
        if not isinstance(v, dict):  # 旧格式：只有一句写法
            v = {"note": v}
        own = _bigrams(_member_text(1, by_id[i]))  # 版本只按自己这一条的原文核对
        lab, note = _text(v.get("label"), 8), _text(v.get("note"), 200)
        if lab and not (_bigrams(lab) & own):
            lab = ""  # 版本名和这一条原文一个字也对不上：不用，界面上按「版本 N」显示
        if note and not _grounded(note, own):
            note = ""  # 没依据：界面上改显示这一条自己的概括
        if lab or note:
            variants[str(i)] = {"label": lab, "note": note}
    # 共性（主条目的属性 / 详细）要在至少两条成员里都有依据：只有一条成员写到的是那个版本的设定，留在版本里，
    # 否则「只用 ② 版」时会通过主条目把 ① 版的设定带进去
    owns = [_bigrams(_member_text(1, by_id[i])) for i in (same or ids)]
    need = 2 if len(owns) >= 2 else 1

    def common(text: str) -> bool:
        return sum(_grounded(text, own) for own in owns) >= need

    attrs, dropped = {}, []
    if isinstance(data.get("attributes"), dict):
        for k, v in data["attributes"].items():
            k, v = str(k).strip()[:20], _text(v, 300)
            if not k or not v:
                continue
            if common(v):
                attrs[k] = v
            else:
                dropped.append(k)
    # 详细描述按句子过一遍同样的检查
    sentences = [x for x in re.split(r"(?<=[。！？；])", _text(data.get("detail"), 2000)) if x.strip()]
    detail = "".join(x for x in sentences if common(x))
    return {"same": same, "title": _text(data.get("title"), 100), "subtype": _text(data.get("subtype"), 32),
            "summary": _text(data.get("summary"), 300), "detail": detail, "attributes": attrs,
            "tags": [_text(t, 20) for t in data.get("tags") or [] if _text(t, 20)][:8]
            if isinstance(data.get("tags"), list) else [],
            "variants": variants, "droppedAttributes": dropped, "usage": usage, "model": cfg.model}


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[\s\W_]+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _grounded(value: str, corpus: set[str]) -> bool:
    """属性值是否有成员原文的依据：它的字符二元组至少 GROUNDED 比例出现在成员文本里"""
    grams = _bigrams(value)
    return bool(grams) and len(grams & corpus) / len(grams) >= GROUNDED
