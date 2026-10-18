# -*- coding: utf-8 -*-
"""errkit.py — 统一友好报错（提升非技术用户的可定位性，对应 TRACE 的 R·可靠性）。

把 Python 常见异常翻译成「中文报错 + 原因 + 怎么修」三段式，避免对普通用户甩一长串 traceback。
各脚本用 `safe_main(main)` 包裹入口即可：脚本内部抛出的未捕获异常会被统一翻译。
pipeline.py 的 `hint_from_stderr()` 复用同一套「怎么修」速查，把单步失败也翻译成人话。

设计原则：
- 只捕获 Exception（不捕获 SystemExit / KeyboardInterrupt），脚本内部 sys.exit(n) 主动退出不受影响。
- 技术细节折叠在最后，供高级用户贴给开发者协助定位，普通用户看前三段即可。
"""
import sys
import traceback


def diagnose(exc):
    """把异常映射为 (标题, 原因, 修复建议) 三元组。"""
    from zipfile import BadZipFile
    etype = type(exc).__name__
    msg = str(exc) or etype

    if isinstance(exc, ModuleNotFoundError):
        mod = getattr(exc, "name", "") or ""
        if mod in ("docx", "python-docx"):
            return ("依赖未安装：缺少 python-docx",
                    "脚本需要 python-docx 来读写 .docx，但当前 Python 环境里没装。",
                    "运行技能目录下的 setup.bat（Windows）或 ./setup.sh（macOS/Linux）一键装好；"
                    "或手动：python -m pip install python-docx")
        if mod in ("PIL", "Pillow"):
            return ("依赖未安装：缺少 Pillow",
                    "封面指标核查需要 Pillow，但当前环境里没装。",
                    "运行 setup.bat / setup.sh，或 python -m pip install Pillow"
                    "（封面核查可跳过，不影响去 AI 味主流程）。")
        return ("依赖未安装：缺少模块 %s" % mod,
                "脚本导入 %s 失败。" % mod,
                "运行 setup.bat / setup.sh 安装技能依赖后重试。")

    if isinstance(exc, BadZipFile):
        return ("文件不是有效的 .docx 或已损坏",
                "该文件无法以 docx(zip) 格式解压，可能是文件损坏、被改了后缀，或根本不是 Word 文档。",
                "确认源文件是 Word「另存为」的 .docx（不是 .doc / .txt / 压缩包）；"
                "若从微信 / 网盘下载，重新下载一次再试。")

    if "不是有效的" in msg or "已损坏" in msg or "package not found" in msg.lower():
        return ("文件不是有效的 .docx 或已损坏",
                str(exc),
                "确认源文件是 Word「另存为」的 .docx（不是 .doc / .txt / 压缩包）；"
                "若从微信 / 网盘下载，重新下载一次再试。")

    if isinstance(exc, FileNotFoundError):
        return ("找不到文件",
                "指定的路径不存在：%s" % msg,
                "检查路径是否拼写正确、是否用了绝对路径；把文件直接拖进终端时记得给路径加引号。")

    if isinstance(exc, PermissionError):
        return ("文件被占用，无法读写",
                "没有权限访问该文件：%s" % msg,
                "关闭正在打开它的 Word / WPS / 资源管理器窗口，或把文件复制到别的目录再跑。")

    if "docx" in msg or "损坏" in msg or "有效" in msg or "不是" in msg:
        return ("文件打不开", msg,
                "确认是有效的 .docx；若损坏请从源重新获取。")

    return ("运行出错", msg,
            "把上方这段红字发给我，我帮你定位；或先跑 run_tests.bat 确认环境没有问题。")


def safe_main(func):
    """包裹脚本入口：正常调用 func()；异常时打印友好三段式并以退出码 1 结束。

    只捕获 Exception（不捕获 SystemExit / KeyboardInterrupt），
    因此脚本内部用 sys.exit(n) 主动退出的行为不受影响。
    友好报错统一输出到 stderr，便于上游（如 pipeline）捕获并二次翻译。
    """
    try:
        func()
    except Exception as e:  # noqa: BLE001
        title, cause, fix = diagnose(e)
        err = sys.stderr
        err.write("=" * 56 + "\n")
        err.write("⚠️ %s\n" % title)
        err.write("-" * 56 + "\n")
        err.write("原因：%s\n" % cause)
        err.write("怎么修：%s\n" % fix)
        tb = getattr(e, "__traceback__", None)
        if tb is not None:
            detail = "".join(traceback.format_exception(type(e), e, tb)).strip()
            err.write("-" * 56 + "\n")
            err.write("技术细节（可忽略；或贴给开发者协助定位）：\n")
            err.write(detail + "\n")
        err.write("=" * 56 + "\n")
        sys.exit(1)
    return None


def hint_from_stderr(stderr):
    """给 pipeline 的某步失败 stderr 配一句「怎么修」速查（关键词匹配）。

    子脚本已用 safe_main 输出「⚠️ 标题 / 原因 / 怎么修」三段式，
    这里复用同样的关键词，把单步失败也翻译成人话，而非甩原始 traceback。
    """
    s = (stderr or "").lower()
    if ("依赖未安装" in s or "modulenotfounderror" in s or "no module named" in s):
        return "可能缺依赖：运行 setup.bat / setup.sh 安装 python-docx 与 Pillow 后重试。"
    if ("不是有效的" in s or "已损坏" in s or "package not found" in s
            or "badzipfile" in s or "not a zip" in s):
        return "源文件可能不是有效的 .docx 或已损坏：确认是 Word「另存为」的 .docx，损坏请重新获取。"
    if "找不到文件" in s or "filenotfounderror" in s or "no such file" in s:
        return "路径不对：检查源文件路径是否拼写正确、是否用了绝对路径。"
    if "被占用" in s or "permissionerror" in s or "permission" in s:
        return "文件被占用：关闭打开它的 Word / WPS 后重试，或换个目录。"
    if "怎么修" in s:
        # 子脚本已输出友好三段式，直接提示看上方红字即可
        return "该步骤已给出「原因 + 怎么修」（见上方红字）；按提示处理后再重跑本步。"
    if "error" in s or "traceback" in s:
        return "该步骤报错（详见上方红字）。多数情况重跑 setup 或换源文件即可；仍不行把它发我。"
    return "该步骤未正常完成（详见上方输出）。可单独重跑本步，或把报告发我协助定位。"
