"""中文关键词检索（BM25 + jieba 分词），作为向量检索之外的另一路召回。

- 中文必须先分词：按标点切的整串当一个词时，「笑里藏刀」搜不到「笑里藏刀的圣女」（memvid 的 Tantivy 就是这样）
- 查询词之间是「或」：多出一个文档里没有的词（如「……的女子」）不会让结果变成空
- 文档的分词结果按文本 SHA-1 缓存；同一批文档（键集合相同）的倒排统计也缓存，素材库检索时基本只算查询
- 网文用语（退婚、扮猪吃虎、金手指……）jieba 词典里没有：调用方把素材标签作为词表（vocab）传入，加进 jieba，
  另有少量内置词（BUILTIN_WORDS）；词表变化时清空分词缓存
- 只依赖 jieba（纯 Python），不需要 torch
"""
import hashlib
import math
import re
import threading
from collections import Counter, OrderedDict

K1, B = 1.5, 0.75
_WORD = re.compile(r"[\w一-鿿]")
# 高频虚词：去掉后 BM25 不会被「的 / 了 / 是」拉分
STOPWORDS = set("的 了 是 在 和 与 及 或 被 把 将 对 为 也 都 而 之 其 这 那 有 无 一个 一种 一些 什么 怎么 如何 可以 能够 想要 需要 相关 素材 适合 那种 这种 一下 比较".split())

_lock = threading.Lock()
_tok_cache: OrderedDict[str, Counter] = OrderedDict()   # 文本键 → 词频
_TOK_CACHE_MAX = 60000
_index_cache: OrderedDict[str, dict] = OrderedDict()     # 文档键集合 → {df, avgdl}
_INDEX_CACHE_MAX = 4
_jieba = None
_vocab: set[str] = set()
BUILTIN_WORDS = ("退婚 废柴 扮猪吃虎 金手指 打脸 逆袭 重生 穿越 系统流 老爷爷 天才 宗门 长老 圣女 魔头 反派 "
                 "主角 外门 内门 亲传 筑基 金丹 元婴 化神 渡劫 灵根 灵气 秘境 传承 夺舍 炼丹 炼器 阵法").split()


def add_vocab(words) -> int:
    """把领域词加进 jieba（2–8 字的词），返回新增个数；有新增时清空分词缓存（旧分词可能已过时）。"""
    _ensure_jieba()
    new = [w.strip() for w in words if w and 2 <= len(w.strip()) <= 8 and w.strip() not in _vocab]
    if not new:
        return 0
    with _lock:
        for w in new:
            _jieba.add_word(w, freq=20000)
            _vocab.add(w)
        _tok_cache.clear()
        _index_cache.clear()
    return len(new)


def _ensure_jieba() -> None:
    global _jieba
    if _jieba is None:
        import jieba

        jieba.setLogLevel(60)  # 不打印「Building prefix dict…」
        _jieba = jieba
        for w in BUILTIN_WORDS:
            jieba.add_word(w, freq=20000)
            _vocab.add(w)


def _cut(text: str) -> list[str]:
    _ensure_jieba()
    out = []
    for w in _jieba.lcut_for_search(text):
        w = w.strip().lower()
        if not w or w in STOPWORDS or not _WORD.search(w):
            continue
        # 单个汉字信息量太低（「刀」「门」），只保留多字词和英文 / 数字
        if len(w) == 1 and "一" <= w <= "鿿":
            continue
        out.append(w)
    return out


def tokens(text: str) -> list[str]:
    """查询分词（去重保序）。"""
    return list(dict.fromkeys(_cut(text)))


def _doc_counts(key: str, text: str) -> Counter:
    with _lock:
        c = _tok_cache.get(key)
        if c is not None:
            _tok_cache.move_to_end(key)
            return c
    c = Counter(_cut(text))
    with _lock:
        _tok_cache[key] = c
        while len(_tok_cache) > _TOK_CACHE_MAX:
            _tok_cache.popitem(last=False)
    return c


def scores(query: str, keys: list[str], texts: list[str]) -> list[float]:
    """每个文档的 BM25 分（与 keys / texts 同序）；查询没有可用的词时全为 0。"""
    q = tokens(query)
    if not q or not texts:
        return [0.0] * len(texts)
    docs = [_doc_counts(k, t) for k, t in zip(keys, texts)]
    sig = hashlib.sha1("\n".join(keys).encode()).hexdigest()
    with _lock:
        idx = _index_cache.get(sig)
        if idx is not None:
            _index_cache.move_to_end(sig)
    if idx is None:
        df: Counter = Counter()
        for d in docs:
            df.update(d.keys())
        idx = {"df": df, "avgdl": (sum(sum(d.values()) for d in docs) / len(docs)) or 1.0}
        with _lock:
            _index_cache[sig] = idx
            while len(_index_cache) > _INDEX_CACHE_MAX:
                _index_cache.popitem(last=False)
    n, avgdl, df = len(docs), idx["avgdl"], idx["df"]
    idf = {w: math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) for w in q if df.get(w)}
    if not idf:
        return [0.0] * len(texts)
    out = []
    for d in docs:
        dl = sum(d.values()) or 1
        s = 0.0
        for w, wi in idf.items():
            tf = d.get(w, 0)
            if tf:
                s += wi * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / avgdl))
        out.append(s)
    return out
