# -*- coding: utf-8 -*-
"""cover_check.py — 封面图客观指标自动核查（降低"封面必须人确认"的门槛）

为什么有这个脚本：
  封面图内容（是否低俗/有无真人肖像/有无第三方 IP）脚本看不见，确实仍须人确认；
  但"尺寸够不够、是不是竖版、格式对不对、是不是纯色默认模板"这些是**可机器测量的**，
  本脚本把它们自动查出来，agent 只需就"真人肖像/第三方IP/政治敏感地标"这 3 项引导式问用户，
  把"必须人确认"从"自己拿尺子量+凭空想"降为"点两下"。

仅做客观指标，不做内容审查：
  ✅ 自动查：文件格式 / 像素尺寸 / 宽高比(竖向3:4) / 文件大小 / 是否接近纯色(疑似默认模板)
  ⚠️ 仍须人确认（脚本给不出结论）：真人肖像 / 第三方 IP 元素 / 政治敏感地标 / 文字占比是否超标

用法:
  python cover_check.py <封面图片路径> [--out 报告.md]
依赖: Pillow（PIL）。缺失时打印安装提示并退出，不影响其他流程。
"""
from errkit import safe_main
import argparse
import os
import sys
from pathlib import Path


def _load_image(path):
    try:
        from PIL import Image
    except ImportError:
        return None, ("本脚本需要 Pillow 才能读取图片。请先安装：\n"
                      "  pip install Pillow\n"
                      "（或在本 skill 的 .venv 中：python -m pip install Pillow）")
    try:
        img = Image.open(path)
        img.load()
        return img, None
    except Exception as e:  # noqa
        return None, f"无法打开图片：{e}"


def _is_near_solid(img, sample=40):
    """抽样像素，判断是否接近纯色（疑似系统默认/未设计封面）。返回 (是否纯色, 主色占比)。"""
    try:
        w, h = img.size
        img = img.convert("RGB")
        step_x = max(1, w // sample)
        step_y = max(1, h // sample)
        colors = {}
        total = 0
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                r, g, b = img.getpixel((x, y))
                # 量化到 5bit 降低抖动
                key = (r >> 3, g >> 3, b >> 3)
                colors[key] = colors.get(key, 0) + 1
                total += 1
        if not colors:
            return False, 0.0
        top = max(colors.values())
        ratio = top / total
        return ratio >= 0.85, round(ratio, 2)
    except Exception:  # noqa
        return False, 0.0


def check(path, out_md=None):
    p = Path(path)
    if not p.exists():
        print(f"封面文件不存在: {path}")
        sys.exit(2)

    lines = ["# 封面客观指标核查报告", "", f"- 文件: `{p.name}`", ""]
    lines.append("## 自动核查（机器可测）")
    lines.append("")
    lines.append("| 指标 | 实测 | 建议标准 | 结论 |")
    lines.append("|---|---|---|---|")

    img, err = _load_image(path)
    if img is None:
        lines.append(f"| 图片读取 | 失败 | - | ⚠️ {err} |")
        lines.append("")
        lines.append("> ⚠️ 无法读取图片，客观指标跳过；封面仍需你人工确认全部项。")
        text = "\n".join(lines)
        if out_md:
            Path(out_md).write_text(text, encoding="utf-8")
        print(text)
        return

    w, h = img.size
    fmt = (img.format or os.path.splitext(p.name)[1].lstrip(".").upper() or "未知")
    size_kb = p.stat().st_size / 1024.0

    # 1) 格式
    fmt_ok = fmt in ("JPEG", "JPG", "PNG", "WEBP")
    lines.append(f"| 格式 | {fmt} | JPG/PNG/WEBP | {'✅' if fmt_ok else '⚠️ 建议转 JPG/PNG'} |")

    # 2) 尺寸（推荐 ≥600×800）
    dim_ok = (w >= 600 and h >= 800)
    dim_note = f"{w}×{h}"
    if not dim_ok:
        dim_note += "（建议 ≥600×800，过小会被压缩模糊）"
    lines.append(f"| 像素尺寸 | {w}×{h} | ≥600×800 | {'✅' if dim_ok else '⚠️'} |")

    # 3) 宽高比（竖向 3:4 ≈ 0.75 最佳）
    ratio = w / h if h else 0
    ratio_ok = 0.6 <= ratio <= 0.85
    lines.append(f"| 宽高比(宽/高) | {ratio:.2f} | 0.6–0.85（竖向 3:4 最佳） | "
                 f"{'✅' if ratio_ok else '⚠️ 建议竖向封面'} |")

    # 4) 文件大小
    size_ok = size_kb <= 5 * 1024
    lines.append(f"| 文件大小 | {size_kb:.0f} KB | ≤5 MB | {'✅' if size_ok else '⚠️ 过大，上传可能被拒'} |")

    # 5) 是否接近纯色（疑似默认模板）
    solid, top_ratio = _is_near_solid(img)
    if solid:
        lines.append(f"| 色彩分布 | 主色占比 {top_ratio} | 应具设计层次 | ⚠️ 接近纯色，疑似未设计/默认模板封面 |")
    else:
        lines.append(f"| 色彩分布 | 主色占比 {top_ratio} | 应具设计层次 | ✅ 有层次 |")

    lines.append("")
    lines.append("## 仍须你确认（脚本给不出结论，需人工/agent 引导确认）")
    lines.append("")
    lines.append("以下 3 项**封面图内容**脚本看不见，请据实确认（agent 会用选择题式提问，不用你写长文）：")
    lines.append("")
    lines.append("1. ☐ **真人肖像**：封面是否使用了真人照片/明星脸？→ 须用原创绘制，禁用真人。")
    lines.append("2. ☐ **第三方 IP 元素**：封面是否含他人作品/品牌/动漫游戏角色（如未授权 logo、知名角色剪影）？")
    lines.append("3. ☐ **政治敏感地标/元素**：是否含敏感建筑、旗帜、标语等？")
    lines.append("4. ☐ **文字占比**：书名+笔名文字是否超过画面 15%？（此项可由你目测，脚本无法 OCR）")
    lines.append("")
    lines.append("> 封面图内容（低俗/真人/第三方IP）违规的后果量级大于内容驳回，务必在提交前确认。")
    lines.append("> 客观指标（尺寸/格式/比例/大小）已如上自动查完，无需你手测。")

    text = "\n".join(lines)
    if out_md:
        Path(out_md).write_text(text, encoding="utf-8")
    print(text)


def main():
    ap = argparse.ArgumentParser(description="封面客观指标自动核查")
    ap.add_argument("cover", help="封面图片路径")
    ap.add_argument("--out", help="报告输出 .md 路径")
    args = ap.parse_args()
    check(args.cover, args.out)


if __name__ == "__main__":
    safe_main(main)

