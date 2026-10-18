# -*- coding: utf-8 -*-
"""Extract plain text from a .docx for diagnostics / verification.

Usage:
    python extract_docx.py <input.docx> [output.txt]

Writes one paragraph per line (paragraph index implicit by line number),
so downstream scripts can map "line N" back to the manuscript.

报错统一走 errkit.safe_main：损坏 / 非 docx / 路径错误 / 文件被占用都给出
「中文报错 + 原因 + 怎么修」三段式，不甩 traceback。
"""
import sys
from docx import Document

from errkit import safe_main

NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract(path):
    try:
        doc = Document(path)
    except Exception as e:  # noqa: BLE001
        # 把底层异常翻译成人话（zip 损坏 / 非 docx / 路径问题等）
        s = str(e).lower()
        if ("package not found" in s or "not a zip" in s
                or "badzipfile" in s or "corrupt" in s or "invalid" in s):
            raise ValueError(f"文件不是有效的 .docx 或已损坏：{path}")
        raise ValueError(f"无法打开文件：{path}（{e}）")
    out = []
    for p in doc.paragraphs:
        out.append(p.text)
    # include table cells (rare in novels, but be safe)
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    out.append(p.text)
    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: extract_docx.py <输入.docx> [输出.txt]")
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src + ".txt"
    text = extract(src)  # 异常（损坏/非docx/被占用）由 safe_main 统一翻成人话
    try:
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        raise ValueError(f"无法写入输出文件 {dst}：{e}")
    print(f"extracted {len(text)} chars -> {dst}")


if __name__ == "__main__":
    safe_main(main)
