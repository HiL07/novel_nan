# -*- coding: utf-8 -*-
"""precheck.py — 开跑前预检（**事前校验**，与 errkit 的事后翻译互补）

`errkit.safe_main` 是"出异常之后把 traceback 翻译成人话"；本模块是"**还没开始就
先把常见问题查出来**"，避免流水线跑一半才甩出 Python 原生异常。

预检项（按序，命中阻塞项即停）：
  1. 文件是否存在 / 路径是否正确
  2. 是不是文件（而不是目录）
  3. 是不是 .docx 后缀（.doc / .txt 单独提示"另存为"）
  4. 是不是空文件
  5. 是否过大（>200MB，仅警告）
  6. 是否为有效 zip（不可解压 = 被改后缀 / 已损坏）
  7. zip 内是否含 word/document.xml（排除假 docx）
  8. 是否可读（被 Word/WPS 占用 / 权限不足）
  9. 依赖是否安装：python-docx（阻塞）、Pillow（可选，仅警告）

输出：每项均为「⚠️ 标题 / 原因 / 怎么修」三段式中文提示。

用法:
  python precheck.py <src.docx>

退出码: 0 = 预检通过（可能有警告）；1 = 有必须先解决的阻塞问题；2 = 用法错误
"""
from errkit import safe_main
import os
import sys
import zipfile

DOCX_MEMBER = "word/document.xml"
MAX_SIZE_MB = 200


def check(src):
    """预检一个源文件。

    返回 (blockers, warnings)，每项均为 (标题, 原因, 怎么修) 三元组。
    blockers 非空表示**不建议继续**，应修好后再跑。
    """
    blockers, warns = [], []
    p = str(src)

    # 1) 存在性
    if not os.path.exists(p):
        blockers.append(("文件不存在",
                         f"路径 {p} 找不到这个文件或目录。",
                         "检查路径拼写是否正确、是否用了绝对路径；含空格或中文的路径记得给整段路径加引号。"))
        return blockers, warns

    # 2) 是文件而非目录
    if not os.path.isfile(p):
        blockers.append(("这不是一个文件",
                         f"{p} 是文件夹，不是 .docx 文件。",
                         "把命令最后一个参数换成具体的 .docx 文件路径，而不是文件夹。"))
        return blockers, warns

    # 3) 后缀
    if not p.lower().endswith(".docx"):
        ext = os.path.splitext(p)[1] or "（无后缀）"
        if ext.lower() == ".doc":
            blockers.append(("这是旧版 .doc 格式",
                             "本 skill 只处理 .docx，旧版 .doc 读不了。",
                             "用 Word / WPS 打开后选「另存为」→「Word 文档 (.docx)」，再重新跑。"))
        else:
            blockers.append((f"不是 .docx 文件（{ext}）",
                             "本 skill 的输入必须是 .docx。",
                             "把小说存成 .docx 再跑；若是 .txt / .doc，先用 Word / WPS 另存为 .docx。"))
        return blockers, warns

    # 4) 空文件
    size = os.path.getsize(p)
    if size == 0:
        blockers.append(("文件是空的",
                         "该文件大小为 0 字节，没有任何内容。",
                         "可能是下载或复制中断；重新获取一份完整的 .docx 再跑。"))
        return blockers, warns

    # 5) 过大（仅警告）
    if size > MAX_SIZE_MB * 1024 * 1024:
        warns.append(("文件较大",
                      f"文件约 {size / 1024 / 1024:.0f} MB，处理会较慢、占用较多内存。",
                      "若只是试跑，可先切出前几章做成小样；正式跑请耐心等待。"))

    # 6) 是否为有效 zip
    if not zipfile.is_zipfile(p):
        blockers.append(("不是有效的 .docx 或已损坏",
                         "该文件无法以 docx(zip) 格式解压，可能被改了后缀或已损坏。",
                         "确认是 Word「另存为」的 .docx（不是 .doc / .txt / 压缩包）；"
                         "从微信 / 网盘下载的请重新下载一次。"))
        return blockers, warns

    # 7) 是否含 word/document.xml
    try:
        with zipfile.ZipFile(p) as z:
            if DOCX_MEMBER not in z.namelist():
                blockers.append(("不是有效的 Word 文档",
                                 "压缩包里没有 word/document.xml，不是正常的 .docx。",
                                 "确认是 Word / WPS 生成的 .docx；WPS 请选「Word 文档 (.docx)」而非其他格式。"))
                return blockers, warns
    except Exception as e:  # noqa: BLE001
        blockers.append(("无法读取文件",
                         f"打开时出错：{e}",
                         "文件可能损坏，或正被其他程序占用；关闭占用它的程序后重试。"))
        return blockers, warns

    # 8) 可读性（被占用 / 权限）
    try:
        with open(p, "rb"):
            pass
    except PermissionError:
        blockers.append(("文件被占用或没有读取权限",
                         "系统拒绝读取，通常是该文件正被 Word / WPS 打开。",
                         "关闭打开它的 Word / WPS 后重试，或把文件复制到另一个目录再跑。"))
        return blockers, warns

    # 9) 依赖
    try:
        import docx  # noqa: F401
    except ImportError:
        blockers.append(("缺依赖 python-docx",
                         "没有安装 python-docx，所有脚本都无法运行。",
                         "运行 setup.bat（macOS / Linux 用 setup.sh）安装 python-docx 与 Pillow 后重试。"))
        return blockers, warns

    try:
        import PIL  # noqa: F401
    except ImportError:
        warns.append(("未安装 Pillow（可选）",
                      "Pillow 缺失时封面核查 cover_check.py 不可用，其余功能不受影响。",
                      "想自动查封面指标就跑 setup.bat 装上 Pillow；不用封面功能可忽略。"))

    return blockers, warns


def main():
    if len(sys.argv) < 2:
        print("usage: precheck.py <src.docx>")
        sys.exit(2)
    src = sys.argv[1]
    blockers, warns = check(src)

    print("=" * 56)
    print("开跑前预检（事前校验，避免跑一半才报错）")
    print("=" * 56)
    print(f"目标文件: {src}")

    if blockers:
        print(f"\n❌ 发现 {len(blockers)} 个必须先解决的问题：\n")
        for i, (t, c, f) in enumerate(blockers, 1):
            print(f"{i}. ⚠️ {t}")
            print(f"   原因：{c}")
            print(f"   怎么修：{f}")
        print("\n按上面修好后，再重新运行流水线。")
        print("=" * 56)
        sys.exit(1)

    print("\n✅ 预检通过：文件可以正常处理。")
    for t, c, f in warns:
        print(f"\n⚠️ {t}\n   原因：{c}\n   怎么修：{f}")
    print("=" * 56)


if __name__ == "__main__":
    safe_main(main)
