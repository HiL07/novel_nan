"""从 Java 后端拉取文件并转成纯文本，再切分章节 / 分块。"""
import io
import re

from . import config

# ---------------------------------------------------------------- 章节标题识别
# 规则与 Java backend/.../service/ChapterCounter.java 一致（两边一起改），说明见 docs/素材提取改造方案.md 第二节。
# 逐行判断（行首尾空白去掉后整行匹配）：
#   chapter  「第X章 / 回 / 节 / 话」「Chapter 12 / IV / One」
#   volume   「第X卷 / 集 / 部 / 篇」「卷X」「上部　面壁者」——书里有章级标题时只用来断开，不算章；没有章级标题时当章
#   special  序章 / 楔子 / 尾声 / 番外 …（单靠它们不算有章节结构）
# 标题前可带「正文 / 正文卷 / VIP章节」前缀（去掉）；编号后面的部分像正文（带「。」，或没有分隔就接「，；！？」）时不算标题。
_EN_NUM = r"(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[a-z]+teen|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ][a-z]+)?)"
_NUM = r"[零〇一二三四五六七八九十百千万两\d０-９]+"
_PREFIX_RE = re.compile(r"^(?:正文卷|正文|VIP[ \t　]*章节)[ \t　]*", re.IGNORECASE)
_CHAPTER_HEAD = re.compile(rf"^(第[ \t　]*{_NUM}[ \t　]*[章回节话])(.{{0,30}})$")
_VOLUME_HEAD = re.compile(rf"^(第[ \t　]*{_NUM}[ \t　]*[卷集部篇]|卷[ \t　]*{_NUM})(.{{0,30}})$")
_EMBEDDED_CHAPTER = re.compile(rf"第[ \t　]*{_NUM}[ \t　]*[章回节话]")
_PART_HEAD = re.compile(r"^[上中下]部[ \t　]+[^\s，。！？“”：；…][^，。！？“”：；…]{0,15}$")  # 「上部　面壁者」
_EN_HEAD = re.compile(rf"^(chapter[ \t]+{_EN_NUM})\b(.{{0,60}})$", re.IGNORECASE)
_SPECIAL_CORE = r"(?:序[ \t　]*章|序言|序|前言|楔子|引子|尾[ \t　]*声|后[ \t　]*记|番外|prologue|epilogue)"
_SPECIAL_HEAD = re.compile(rf"^({_SPECIAL_CORE})(.{{0,20}})$", re.IGNORECASE)
_SEPARATORS = " \t　:：、.．-—·（(【[《"
# 兜底：「1.疯狂年代」「一、科学边界」式编号标题——不缩进、短、不以句末标点结尾
NUMBERED_RE = re.compile(
    r"^((?:\d{1,4}|[一二三四五六七八九十百]{1,4})[.、．][ \t]*[^\s\d][^\n]{0,24}?|" + _SPECIAL_CORE + r")[ \t]*$(?<![。！？!?”…：:，,；;])",
    re.IGNORECASE | re.MULTILINE,
)

OPENING_MIN_CHARS = 1500      # 首个标题前的文字至少这么长才算「开篇」章，否则是书头（书名 / 作者 / 简介）
VOLUME_INTRO_MIN_CHARS = 200  # 卷标题后的卷简介至少这么长才保留为一章
SEGMENT_CHARS = 5000          # 没有章节标题时按这么长分段
SHORT_CHAPTER_CHARS = 200     # 超过 1/3 的章短于这个字数时发警告


def _rest_is_prose(rest: str, strict: bool, extra_sep: str = "") -> bool:
    """标题编号后面的部分像正文。先分隔（空格、冒号…）再写的标题不判（实测有「第505章 好消息，有神。坏消息，邪神」「第666章 6。」）。
    没有分隔时：
    - 章级（strict=False）：带句号「。」、引号、或以英文句点结尾才算正文——网文常把标题直接接在「章」后面并带问号叹号逗号
      （「第97章你他娘是个流民？」「第十章杀！」「第493章前辈，他凭什么听你的？！」都是真标题）；
    - 卷级 / 特殊标题（strict=True）：带任何句中、句末标点都算正文（「第一部分为灵性，…」「第一篇论文就是这个？！」）。"""
    if not rest or rest[0] in _SEPARATORS + extra_sep:
        return False
    if strict:
        return re.search(r"[。！？!?…，,；;]", rest) is not None
    return "。" in rest or rest.endswith(".")  # 引号不算：「第一百三十七章龙王收“徒”(上)」是真标题


def detect_heading(line: str) -> tuple[str, str] | None:
    """一行是不是章节标题 → (kind chapter|volume|special, 标题) 或 None。"""
    s = line.strip()
    if not s or len(s) > 50:
        return None
    s = _PREFIX_RE.sub("", s)
    m = _CHAPTER_HEAD.match(s)
    if m and not _rest_is_prose(m.group(2), False):
        return "chapter", s
    m = _EN_HEAD.match(s)
    if m and not _rest_is_prose(m.group(2), False, ","):  # 英文「Chapter 1, The Boy」逗号是分隔
        return "chapter", s
    m = _VOLUME_HEAD.match(s)
    if m:
        # 「第二十七卷红色星期五第十六章红色的恶灵们（一）」：卷名后面带着章号，是章标题（下载站常把卷 + 章写在一行）
        if _EMBEDDED_CHAPTER.search(m.group(2)):
            return "chapter", s
        if not _rest_is_prose(m.group(2), True):
            return "volume", s
    if _PART_HEAD.match(s):
        return "volume", s
    m = _SPECIAL_HEAD.match(s)
    if m:
        rest = m.group(2)
        # 番外后面常直接接名字（「番外篇」「番外一」）；其他特殊标题后面必须先接分隔符
        if (not rest or rest[0] in _SEPARATORS or m.group(1) == "番外") and not _rest_is_prose(rest, True):
            return "special", s
    return None


def fetch_file(file_id: int) -> bytes:
    """通过 Java 后端的预览接口读取原始字节（不直接访问磁盘 / 数据库）。"""
    import httpx  # 延迟导入：训练 worker（含远程执行）只用到本模块的章节切分

    url = f"{config.JAVA_BACKEND_URL}/api/file/preview/{file_id}"
    # trust_env=False：本机服务不走系统代理（Clash 等代理会把 localhost 请求转成 502）
    resp = httpx.get(url, timeout=60, trust_env=False)
    if resp.status_code == 404:
        raise ValueError(f"文件不存在：{file_id}")
    resp.raise_for_status()
    return resp.content


def decode_text(data: bytes) -> str:
    """中文 txt 常见 UTF-8 / GBK 混用：先认 BOM，再严格 UTF-8 → 严格 GB18030；
    都不合法（个别坏字节）时选替换字符更少的那个，避免把 UTF-8 误当 GBK 解成整篇乱码。"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    candidates = [data.decode(enc, errors="replace") for enc in ("utf-8", "gb18030")]
    return min(candidates, key=lambda s: s.count("�"))


def to_plain_text(data: bytes, ext: str) -> str:
    ext = ext.lower()
    if ext in ("txt", "md"):
        text = decode_text(data)
    elif ext == "docx":
        from docx import Document

        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs)
    elif ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raise ValueError(f"不支持的文件类型：{ext}")
    return clean_text(text)


def clean_text(text: str) -> str:
    """统一换行、去行尾空白、压缩多余空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _find_heads(text: str) -> list[tuple[int, int, str, str]]:
    """全部标题行 → [(行首位置, 行尾位置, kind, 标题)]。"""
    heads, pos = [], 0
    for line in text.split("\n"):
        h = detect_heading(line)
        if h:
            heads.append((pos, pos + len(line), h[0], h[1]))
        pos += len(line) + 1
    return heads


def find_headings(text: str) -> list[tuple[int, int, str, str]]:
    """决定用哪一套标题切分：
    有章级标题（chapter）→ 卷标题只断开；没有章级、只有卷级 → 卷标题当章；都没有 → 编号标题兜底（至少 3 处）。
    特殊标题（序章 / 尾声…）跟着用，但单靠它们不算有章节结构。"""
    heads = _find_heads(text)
    if any(k == "chapter" for _, _, k, _ in heads):
        return heads
    if any(k == "volume" for _, _, k, _ in heads):
        return [(s, e, "chapter" if k == "volume" else k, t) for s, e, k, t in heads]
    numbered = []
    for m in NUMBERED_RE.finditer(text):
        title = m.group(1).strip()
        kind = "special" if re.fullmatch(_SPECIAL_CORE, title, re.IGNORECASE) else "chapter"
        numbered.append((m.start(), m.end(), kind, title))
    if sum(1 for _, _, k, _ in numbered if k == "chapter") >= 3:
        return numbered
    return []


def split_book(text: str, *, segment: bool = True) -> dict:
    """按章节标题切分 → {chapters: [{title, content, kind, volume?}], preface, headings, warnings}。
    kind：chapter / special（序章、尾声…）/ volume（卷简介，保留时）/ opening（首个标题前的长文字）/ segment（没有标题时按字数分的段）/ whole。
    preface：首个标题前不到 OPENING_MIN_CHARS 的书头文字（书名、作者、简介），不算章。
    segment=False：没有标题时不分段，整篇一章（训练分组用）。"""
    heads = find_headings(text)
    warnings: list[str] = []
    if not heads:
        body = text.strip()
        if segment and len(body) > SEGMENT_CHARS:
            parts = split_chunks(body, SEGMENT_CHARS)
            warnings.append(f"没有识别到章节标题，已按约 {SEGMENT_CHARS} 字一段分成 {len(parts)} 段")
            return {"chapters": [{"title": f"第 {i} 段", "content": p, "kind": "segment"} for i, p in enumerate(parts, 1)],
                    "preface": "", "headings": 0, "warnings": warnings}
        return {"chapters": [{"title": "全文", "content": text, "kind": "whole"}] if body else [],
                "preface": "", "headings": 0, "warnings": warnings}

    chapters: list[dict] = []
    preface = text[: heads[0][0]].strip()
    if len(preface) >= OPENING_MIN_CHARS:
        chapters.append({"title": "开篇", "content": preface, "kind": "opening"})
        warnings.append("第一个章节标题之前有一大段正文，已单独作为「开篇」")
        preface = ""
    volume, empty = "", 0
    for i, (_, end_of_head, kind, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        content = text[end_of_head:end].strip()
        if kind == "volume":
            volume = title
            if len(content) >= VOLUME_INTRO_MIN_CHARS:
                chapters.append({"title": title, "content": content, "kind": "volume", "volume": title})
            continue
        if not content:
            # 紧跟着同名标题的是下载站重复的章名，照常跳过、不提示；其余多半是目录页或空章
            if not (i + 1 < len(heads) and heads[i + 1][3] == title):
                empty += 1
            continue
        ch = {"title": title, "content": content, "kind": kind}
        if volume:
            ch["volume"] = volume
        chapters.append(ch)
    if empty:
        warnings.append(f"跳过了 {empty} 个没有正文的标题（目录页或空章）")
    # 有正文的卷也算一个单元：《三体》二三部只有「上部 / 第一部」没有章，正文都在卷下（卷简介不到 200 字的已丢掉）
    real = [c for c in chapters if c["kind"] in ("chapter", "special", "volume")]
    short = sum(1 for c in real if len(c["content"]) < SHORT_CHAPTER_CHARS)
    if len(real) >= 3 and short * 3 > len(real):
        warnings.append(f"有 {short} 章不到 {SHORT_CHAPTER_CHARS} 字，请确认分章是否正确")
    return {"chapters": chapters, "preface": preface, "headings": len(real), "warnings": warnings}


def split_chapters(text: str) -> list[dict]:
    """按章节标题切分 → [{title, content, kind, volume?}]（规则见 split_book）。识别不到章节、篇幅又短时整篇作为一章。"""
    return split_book(text)["chapters"] or [{"title": "全文", "content": text, "kind": "whole"}]


def count_chapters(text: str) -> int:
    """章节数（与 Java ChapterCounter.count 一致）：有正文的 chapter / special / volume，不含开篇、书头、分段；没有章节结构 = 0。"""
    return split_book(text.replace("\r\n", "\n").replace("\r", "\n"), segment=False)["headings"]


def split_chunks(content: str, limit: int) -> list[str]:
    """超长章节按段落边界切成 ≤ limit 字的块；单段超长则硬切。"""
    if len(content) <= limit:
        return [content]
    chunks, buf = [], ""
    for para in content.split("\n"):
        while len(para) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(para[:limit])
            para = para[limit:]
        if len(buf) + len(para) + 1 > limit:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks
