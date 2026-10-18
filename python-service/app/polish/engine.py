"""适配层：把 vendor/novel_deai 的 docx 流水线拆成纯文本调用。

analyze(text, title, index) → 检测报告（含整章建议稿 suggestedText），不修改输入。
章节正文按行分段（生成的正文一行一段），每段依次过 L1（deai_humanizer.clean）与
L2.5（auto_rewrite.rewrite_paragraph）；评分与风险扫描复用其 scan_* / check_chapter。
"""
import difflib
import logging
import re
import sys
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

log = logging.getLogger("polish")

VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "novel_deai"
SCRIPTS_DIR = VENDOR_DIR / "scripts"
MAX_LIST = 30           # 每类明细最多返回条数
_MIN_PARA = 6           # 与 vendor 一致：短于 6 字的段不扫描

_lock = threading.Lock()
_mods = None


class PolishError(Exception):
    pass


def _vendor():
    """懒加载 vendor 模块（其脚本以顶层模块名互相 import，只能把 scripts/ 加入 sys.path 末尾）。"""
    global _mods
    with _lock:
        if _mods is None:
            if not SCRIPTS_DIR.is_dir():
                raise PolishError(f"未找到去 AI 味规则引擎：{SCRIPTS_DIR}")
            if str(SCRIPTS_DIR) not in sys.path:
                sys.path.append(str(SCRIPTS_DIR))
            try:
                import auto_rewrite, build_map_wizard, copyright_scan, deai_deep_report, deai_humanizer  # noqa: E401
                import eval_fix_check, semantic_scan, wiki_signs_scan  # noqa: E401
            except ImportError as e:
                raise PolishError(f"加载去 AI 味规则引擎失败：{e}（需要 python-docx）") from e
            _mods = {"auto_rewrite": auto_rewrite, "wizard": build_map_wizard, "copyright": copyright_scan,
                     "deep": deai_deep_report, "humanizer": deai_humanizer, "eval": eval_fix_check,
                     "semantic": semantic_scan, "wiki": wiki_signs_scan}
        return _mods


def version() -> str:
    try:
        import json
        return json.loads((VENDOR_DIR / "_meta.json").read_text(encoding="utf-8")).get("version", "")
    except (OSError, ValueError):
        return ""


def _paras(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


_CLAUSE_SPLIT = re.compile(r"[，。！？；：、…,.!?;:]")
_HAN = re.compile(r"[一-鿿]")
_BAD_PUNCT = re.compile(r"[，、；：][，。！？、；：]|^[，。！？、；：]|“[，。！？、；：]")


_SPEECH = {"说", "道", "问", "答", "喊", "叫", "笑", "哭", "骂", "叹"}  # 「X说：」类单字分句是正常对话标签


def _tiny_clauses(s: str) -> set[str]:
    out = set()
    for c in _CLAUSE_SPLIT.split(s):
        c = c.strip(" “”\"‘’「」")
        if c and len(_HAN.findall(c)) <= 1 and c not in _SPEECH:
            out.add(c)
    return out


def _broken(before: str, after: str) -> str:
    """vendor 的删词规则可能把句子删残（「她不禁深吸一口气，…」→「她，…」）。返回原因，空串表示正常。"""
    if not after:
        return "整段被删空"
    if _BAD_PUNCT.search(after) and not _BAD_PUNCT.search(before):
        return "删词后出现连续 / 句首标点"
    if _tiny_clauses(after) - _tiny_clauses(before):
        return "删词后出现残缺分句"
    return ""


# vendor 规则里「删动词留宾语」或「删掉词组一部分」的条目：直接用会把句子删残，适配层不采用。
# （按 vendor 规则的 pattern 原文匹配；vendor 升级后若新增类似条目，在这里补上）
UNSAFE_L1 = {
    "深吸一口气", "心中涌起一股", "心头一震", "心中一动", "心下了然", "心底泛起", "嘴角勾起一抹",
    "眼中闪过一丝", "眼中闪过一抹", "不易察觉", "涌上心头",
}
UNSAFE_L1_PREFIX = ("一股(",)                      # 一股(暖流|杀意…) → 删后「透露出。」
UNSAFE_L25 = {"仿佛", "似乎", "瞬间", "那一刻", "那一刻，"}  # 「在那一瞬间」「眼神仿佛星空」
_LEAD_PUNCT = re.compile(r"(^|(?<=[。！？…”」]))[，、；：]+")


def _rules(m) -> dict:
    """从 vendor 取规则表并去掉不安全条目（只取数据，不改 vendor 文件）。"""
    h, a = m["humanizer"], m["auto_rewrite"]
    for name in ("COMPILED",):
        if not hasattr(h, name):
            raise PolishError(f"vendor deai_humanizer 缺少 {name}，版本不兼容")
    for name in ("EXTRA_FILLER", "SIMILE_FIX", "_TAG_RE", "_tag_repl", "_EMO_RE", "_emo_repl", "_TRANS_RE", "_trans_repl"):
        if not hasattr(a, name):
            raise PolishError(f"vendor auto_rewrite 缺少 {name}，版本不兼容")
    l1 = [(rx, rep) for rx, rep in h.COMPILED
          if not (rep == "" and (rx.pattern in UNSAFE_L1 or rx.pattern.startswith(UNSAFE_L1_PREFIX)))]
    extra = [(re.compile(p), r) for p, r in a.EXTRA_FILLER if p not in UNSAFE_L25]
    return {"l1": l1, "extra": extra, "a": a}


def _apply(s: str, r: dict, stats: Counter) -> str:
    """L1（humanizer.clean 的规则）+ L2.5（auto_rewrite.rewrite_paragraph 的五类改写），顺序与 vendor 一致。"""
    new = s
    for rx, rep in r["l1"]:
        new, n = rx.subn(rep, new)
        stats["L1_filler"] += n
    new = re.sub(r"  +", " ", new)
    new = re.sub(r"\s+([，。！？、])", r"\1", new).replace("（）", "")
    a = r["a"]
    new, n = a._TAG_RE.subn(a._tag_repl, new)
    stats["C_tag_deadv"] += n
    for rx, rep in r["extra"]:
        new, n = rx.subn(rep, new)
        stats["A_ext_filler"] += n
    new, n = a._EMO_RE.subn(a._emo_repl, new)
    stats["B_tell_to_show"] += n
    for sim in sorted(a.SIMILE_FIX, key=len, reverse=True):
        if sim in new:
            new = new.replace(sim, a.SIMILE_FIX[sim])
            stats["D_simile"] += 1
    new, n = a._TRANS_RE.subn(a._trans_repl, new)
    stats["E_transition"] += n
    # 删掉句首连接词（「不得不说，」「毫无疑问，」）后留下的句首逗号
    return _LEAD_PUNCT.sub("", new).strip()


def _rewrite(text: str, m) -> tuple[str, list[dict], list[dict], Counter]:
    """逐行改写，保留原有换行结构。仍被改坏的行保留原文并列入 skipped。
    返回 (建议稿, 改动明细, 跳过明细, 改写统计)。"""
    rules = _rules(m)
    stats: Counter = Counter()
    out, changes, skipped = [], [], []
    for i, line in enumerate(text.split("\n")):
        s = line.strip()
        if not s:
            out.append(line)
            continue
        line_stats: Counter = Counter()
        new = _apply(s, rules, line_stats)
        if new == s:
            out.append(s)
            continue
        reason = _broken(s, new)
        if reason:
            skipped.append({"line": i + 1, "before": s, "after": new, "reason": reason})
            out.append(s)
            continue
        stats.update({k: v for k, v in line_stats.items() if v})
        changes.append({"line": i + 1, "before": s, "after": new})
        out.append(new)
    return "\n".join(out), changes, skipped, stats


def _concentration(paras: list[str], m) -> tuple[int, Counter, list[dict]]:
    """维基《AI 写作迹象》浓度分（硬 ×2 + 软 ×1）+ 命中明细。"""
    hard, soft, hits = Counter(), Counter(), []
    for p in paras:
        if len(p) < _MIN_PARA:
            continue
        for typ, reason, word, is_soft in m["wiki"].scan_paragraph(p):
            (soft if is_soft else hard)[typ] += 1
            hits.append({"type": typ, "reason": reason, "word": word, "soft": is_soft, "snippet": _snip(p)})
    return m["wiki"].concentration_score(hard, soft), hard + soft, hits


def _deep(title: str, paras: list[str], m) -> list[dict]:
    """L2 九项深层诊断（第一段视为标题行，与 vendor 解析一致）。"""
    issues, _ = m["deep"].check_chapter({"num": 0, "title": title, "paras": [title] + paras})
    return [{"level": lv, "category": c, "detail": d} for lv, c, d in issues]


def _scan(paras: list[str], fn) -> list[dict]:
    out = []
    for p in paras:
        if len(p) < _MIN_PARA:
            continue
        for typ, reason, word in fn(p):
            out.append({"type": typ, "reason": reason, "word": word, "snippet": _snip(p)})
    return out[:MAX_LIST]


def _snip(p: str) -> str:
    return p if len(p) <= 80 else p[:80] + "…"


def analyze(text: str, title: str = "", index: int = 0) -> dict:
    m = _vendor()
    paras = _paras(text)
    suggested, changes, skipped, stats = _rewrite(text, m)
    new_paras = _paras(suggested)
    score_before, signals, wiki_hits = _concentration(paras, m)
    score_after, _, _ = _concentration(new_paras, m)
    deep_before, deep_after = _deep(title, paras, m), _deep(title, new_paras, m)
    eval_issues, han = m["eval"].check_chapter(index, title, [title] + new_paras)
    redline = m["wizard"].scan_triggers(suggested)
    change_rate = 1 - difflib.SequenceMatcher(None, text, suggested, autojunk=False).ratio() if changes else 0.0
    return {
        "engine": f"novel-deai-tomato-pass {version()}",
        "checkedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "applied": False,
        # 去 AI 味：浓度分（越低越好）与 L2 问题数，改写前 → 建议稿
        "score": {"before": score_before, "after": score_after,
                  "deepBefore": len(deep_before), "deepAfter": len(deep_after)},
        "changeCount": len(changes),
        "changeRate": round(change_rate, 4),   # 改动率：番茄口径 < 10% 属语言润色
        "stats": dict(stats),
        "changes": changes[:200],
        "skipped": skipped[:MAX_LIST],         # 规则改坏的行：建议稿里保留原文，需手改
        "suggestedText": suggested,
        # 以下针对建议稿（应用后要发布的文本）
        "deepIssues": deep_after,
        "signals": dict(signals),
        "wikiHits": wiki_hits[:MAX_LIST],
        "evalIssues": [{"level": lv, "category": c, "detail": d} for lv, c, d in eval_issues],
        "hanCount": han,
        "redline": [{"group": g, **h} for g, hits in redline.items() for h in hits],
        "semantic": _scan(new_paras, m["semantic"].scan_paragraph),
        "copyright": _scan(new_paras, m["copyright"].scan_paragraph),
    }


def safe_analyze(text: str, title: str = "", index: int = 0) -> dict:
    """生成流程里调用：检测失败只记录错误，绝不影响章节本身。"""
    try:
        return analyze(text, title, index)
    except Exception as e:  # noqa: BLE001
        log.exception("去 AI 味检测失败（第 %s 章）", index)
        return {"error": str(e) or e.__class__.__name__, "checkedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


if __name__ == "__main__":  # 自检：python -m app.polish.engine
    sys.stdout.reconfigure(encoding="utf-8")
    demo = ("就在这时，他顿时感到一阵愤怒，嘴角微微上扬，淡淡地说：“与此同时，我们必须面对这一切。”\n"
            "她不禁深吸一口气，眼中闪过一丝复杂，不仅仅是美丽，更是一种力量。")
    r = analyze(demo, "测试章", 1)
    print(r["engine"], "score", r["score"], "changes", r["changeCount"], "rate", r["changeRate"])
    for c in r["changes"]:
        print(" -", c["before"], "\n  →", c["after"])
    for c in r["skipped"]:
        print(" x", c["reason"], c["before"], "\n  ✗", c["after"])
