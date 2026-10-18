"""验证集划分单元测试（不需要 GPU / 模型 / 服务）：
  .venv/Scripts/python scripts/dataset_split_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.local import dataset  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def chapters(n: int, paras: int = 6, tag: str = "") -> str:
    """n 章互不重复的文本（每段带唯一编号，避免段落级重复干扰泄漏检查）。"""
    out = []
    for c in range(1, n + 1):
        body = "\n".join(f"{tag}第{c}章第{p}段：风从城墙外吹进来，带着潮湿的泥土气味，巡夜人提着灯慢慢走过。"
                         for p in range(1, paras + 1))
        out.append(f"第{c}章 标题{c}\n{body}")
    return "\n\n".join(out)


def sources(*texts):
    return [{"type": "text", "name": f"src{i}", "text": t} for i, t in enumerate(texts)]


# 1. 多章节：按组划分，无交叉，比例接近 5%
groups = dataset.build_groups(sources(chapters(40)))
plan = dataset.split(groups, 0.05, 42)
rep = dataset.report(plan)
ratio = rep["val"]["chars"] / (rep["val"]["chars"] + rep["train"]["chars"])
check("group_mode", plan["mode"] == "group" and rep["val"]["groups"] >= 1, f"val groups={rep['val']['groups']} ratio={ratio:.3f}")
check("group_no_overlap", rep["groupOverlap"] == 0 and rep["paragraphOverlap"] == 0)
check("group_ratio_reasonable", 0.025 <= ratio <= 0.10, f"{ratio:.3f}")
check("group_keeps_titles", all(g["text"].startswith(g["title"]) for g in groups))
check("group_all_text_used", rep["val"]["chars"] + rep["train"]["chars"] == sum(len(g["text"]) for g in groups))

# 2. 确定性：同种子同结果，不同种子可以不同
p2 = dataset.split(groups, 0.05, 42)
check("deterministic", [g["id"] for g in p2["val"]] == [g["id"] for g in plan["val"]])

# 3. 多来源：分组 id 区分来源，跨来源也无交叉
groups_multi = dataset.build_groups(sources(chapters(20, tag="甲"), chapters(20, tag="乙")))
pm = dataset.report(dataset.split(groups_multi, 0.05, 7))
check("multi_source", len(groups_multi) == 40 and pm["groupOverlap"] == 0 and pm["paragraphOverlap"] == 0,
      f"groups={len(groups_multi)} valGroups={[g['id'] for g in pm['valGroups']]}")

# 4. 单章 / 无标题：退化为末尾连续片段，并给出警告
single = "\n".join(f"第{i}行：没有章节标题的一整段正文，写着雨夜里的旧城与归人。" for i in range(400))
ps = dataset.split(dataset.build_groups(sources(single)), 0.05, 42)
rs = dataset.report(ps)
check("tail_fallback", ps["mode"] == "tail" and ps["warnings"] and rs["paragraphOverlap"] == 0,
      f"warn={ps['warnings'][0][:30] if ps['warnings'] else None}")
check("tail_contiguous", dataset.join(ps["train"]) + "\n" + dataset.join(ps["val"]) == single)

# 5. 一个超长章节 + 很多短章：不能整组凑比例时退化
lop = "第1章 长\n" + "\n".join(f"长章第{i}段，絮絮叨叨地讲着同一件事。" for i in range(2000)) + "\n\n" + \
      "\n\n".join(f"第{c}章 短\n短章{c}只有一句话。" for c in range(2, 5))
pl = dataset.split(dataset.build_groups(sources(lop)), 0.05, 42)
rl = dataset.report(pl)
check("skewed_groups_fallback", pl["mode"] == "tail" and pl["warnings"] and rl["groupOverlap"] == 0
      and rl["paragraphOverlap"] == 0 and pl["val"][0]["id"].startswith("0:0"),
      f"mode={pl['mode']} val={pl['val'][0]['id'] if pl['val'] else None} warnings={len(pl['warnings'])}")

# 5b. 全部分组都很短：明确记录 none 及原因，不产出验证集
pt = dataset.split(dataset.build_groups(sources("短")), 0.3, 1)
check("none_with_reason", pt["mode"] == "none" and pt["reason"] and not pt["val"] and len(pt["train"]) == 1,
      f"mode={pt['mode']} reason={pt['reason']}")

# 5c. 只有标题行（正文行也像标题）：不丢文本，整个来源作为一组
only_titles = "\n".join(f"第{c}章只有一句。" for c in range(1, 4))
gt = dataset.build_groups(sources(only_titles))
check("titles_only_kept", len(gt) == 1 and gt[0]["text"] == only_titles, f"groups={len(gt)}")
check("empty_no_crash", dataset.split([], 0.05, 1)["mode"] == "none")

# 6. valRatio = 0
pd = dataset.split(groups, 0.0, 42)
check("disabled", pd["mode"] == "disabled" and not pd["val"] and len(pd["train"]) == len(groups))

# 7. 重复段落会被检测出来（不静默）
dup = chapters(30) + "\n\n" + "\n\n".join(f"第{c}章 重复\n这一段在每一章都完全相同，用来检测泄漏是否会被发现。" for c in range(31, 61))
pdup = dataset.report(dataset.split(dataset.build_groups(sources(dup)), 0.2, 3))
check("paragraph_overlap_detected", pdup["paragraphOverlap"] >= 1, f"overlap={pdup['paragraphOverlap']}")

failed = [n for n, ok in results if not ok]
print("\nSUMMARY", f"{len(results) - len(failed)}/{len(results)} passed", ("FAILED: " + ", ".join(failed)) if failed else "")
sys.exit(1 if failed else 0)
