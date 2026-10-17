"""从 Java 后端拉取文件并转成纯文本，再切分章节 / 分块。"""
import io
import re

import httpx

from . import config

# 章节标题（独占一行）：中文「第X章/回/节/卷…」，英文「Chapter 12 / Chapter IV / Chapter One」
_EN_NUM = r"(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[a-z]+teen|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ][a-z]+)?)"
# 独立成行的特殊段落标题
_SPECIAL = r"(?:序章|序言|序|前言|楔子|引子|尾声|后记|番外[^\n]{0,20}|prologue|epilogue)"
CHAPTER_RE = re.compile(
    r"^[ \t　]*("
    r"第[零〇一二三四五六七八九十百千万两\d]+[章回节卷集部篇][^\n]{0,30}"
    r"|chapter[ \t]+" + _EN_NUM + r"\b[^\n]{0,60}"
    r"|" + _SPECIAL +
    r")[ \t　]*$",
    re.IGNORECASE | re.MULTILINE,
)
# 兜底：「1.疯狂年代」「一、科学边界」式编号标题——不缩进、短、不以句末标点结尾
NUMBERED_RE = re.compile(
    r"^((?:\d{1,4}|[一二三四五六七八九十百]{1,4})[.、．][ \t]*[^\s\d][^\n]{0,24}?|" + _SPECIAL + r")[ \t]*$(?<![。！？!?”…：:，,；;])",
    re.IGNORECASE | re.MULTILINE,
)


def fetch_file(file_id: int) -> bytes:
    """通过 Java 后端的预览接口读取原始字节（不直接访问磁盘 / 数据库）。"""
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


def split_chapters(text: str) -> list[dict]:
    """按章节标题切分；识别不到章节时整篇作为一章。返回 [{title, content}]。
    优先「第X章 / Chapter N」；一个都没有时才用编号标题兜底，且至少 3 处才认，避免把正文编号列表当章节。"""
    matches = [m for m in CHAPTER_RE.finditer(text) if not _is_special_only(m)]
    if matches:
        matches = list(CHAPTER_RE.finditer(text))
    else:
        numbered = [m for m in NUMBERED_RE.finditer(text) if not _is_special_only(m)]
        matches = list(NUMBERED_RE.finditer(text)) if len(numbered) >= 3 else []
    if not matches:
        return [{"title": "全文", "content": text}]

    chapters = []
    preface = text[: matches[0].start()].strip()
    if len(preface) >= 50:  # 太短的通常只是书名行，不值得单独解析
        chapters.append({"title": "序/前言", "content": preface})
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[m.end():end].strip()
        if content:
            chapters.append({"title": m.group(1).strip(), "content": content})
    return chapters


def _is_special_only(m: re.Match) -> bool:
    """只匹配到「前言 / 尾声」等特殊标题的不算章节结构（单靠它们不切分）。"""
    return re.fullmatch(_SPECIAL, m.group(1).strip(), re.IGNORECASE) is not None


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
