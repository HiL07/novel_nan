"""素材提取 v2 评测：同一段样本，比较不同模型 / 阅读遍数的提取效果（不需要 Java、不写数据库）。

用法（在 python-service 目录下）：
  .venv/Scripts/python scripts/extract_eval.py --text 某小说.txt --chapters 1-10 \\
      --run gguf1=http://127.0.0.1:8002/v1,1 --run gguf2=http://127.0.0.1:8002/v1,2 \\
      [--run deepseek=https://api.deepseek.com,1,deepseek-chat,DEEPSEEK_API_KEY] [--baseline deepseek] \\
      [--chunk 3000] [--out 结果.json]

--run 名称=地址,遍数[,模型名[,存 API Key 的环境变量]]：模型名缺省时取服务 /v1/models 的第一个（llama.cpp）。
--baseline：以哪一组的实体为基准计算其他组的实体召回（缺省 = 第一组）。
每组先 scan（提取）再 compile_cards（整理卡片，取事实最多的 --max-candidates 个实体）。
输出：每组耗时（含其中的阅读耗时）、token、块数、事实核实通过 / 丢弃、实体数、卡片数、不实用数、剧情段数、相对基准的实体召回，
并把基准里事实最多的 5 个实体在各组的卡片并排打印。会真实调用模型（大模型按 token 计费）。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import extract_checkpoint, extractor, llm_client, material_facts, text_loader  # noqa: E402
from app.llm_client import ModelConfig  # noqa: E402
from app.materials import MaterialOptions, _norm_title  # noqa: E402


def parse_run(spec: str) -> dict:
    name, _, rest = spec.partition("=")
    parts = rest.split(",")
    if not name or len(parts) < 2:
        raise SystemExit(f"--run 格式不对：{spec}")
    base, rounds = parts[0], int(parts[1])
    model = parts[2] if len(parts) > 2 and parts[2] else ""
    key = os.environ.get(parts[3], "") if len(parts) > 3 and parts[3] else ""
    if not model:
        r = httpx.get(base.rstrip("/") + "/models", timeout=10, trust_env=False).json()
        model = (r.get("data") or r.get("models"))[0].get("id") or (r.get("data") or r.get("models"))[0].get("name")
    return {"name": name, "cfg": ModelConfig(baseUrl=base, apiKey=key, model=model, concurrency=1 if not key else 4),
            "rounds": rounds}


def pick_chapters(text: str, spec: str) -> list[dict]:
    chapters = text_loader.split_chapters(text)
    a, _, b = spec.partition("-")
    return chapters[int(a) - 1:int(b or a)]


def names_of(materials: list[dict]) -> dict[str, dict]:
    out = {}
    for m in materials:
        if m["category"] == "plot":
            continue
        for n in [m["title"], *m.get("aliases", [])]:
            out.setdefault(f"{m['category']}:{_norm_title(n)}", m)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--chapters", default="1-10")
    ap.add_argument("--run", action="append", required=True)
    ap.add_argument("--baseline", default="")
    ap.add_argument("--chunk", type=int, default=3000)
    ap.add_argument("--max-candidates", type=int, default=500)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    text = text_loader.decode_text(Path(args.text).read_bytes())
    chapters = pick_chapters(text, args.chapters)
    chars = sum(len(c["content"]) for c in chapters)
    print(f"样本：{len(chapters)} 章，{chars} 字（{chapters[0]['title']} … {chapters[-1]['title']}）")

    results = {}
    for spec in args.run:
        run = parse_run(spec)
        opts = MaterialOptions(enabled=True, rounds=run["rounds"], chunkChars=args.chunk)
        usage = llm_client.new_usage(run["cfg"])
        call = extractor._chat_fn(run["cfg"], usage)
        start = time.monotonic()
        last = {"t": 0.0}

        def progress(p, msg):
            if time.monotonic() - last["t"] > 15:
                last["t"] = time.monotonic()
                print(f"  [{run['name']}] {p}% {msg}", flush=True)

        scanned = material_facts.scan(chapters, opts, call, run["cfg"].concurrency,
                                      extract_checkpoint.Checkpoint(None, {}), progress, None, local=False)
        scan_seconds = round(time.monotonic() - start, 1)
        rows = [{"title": c["title"], "summary": s["summary"]} for c, s in zip(chapters, scanned["chapters"])]
        out = material_facts.compile_cards(scanned["entities"][:args.max_candidates], rows, call, run["cfg"].concurrency,
                                           extract_checkpoint.Checkpoint(None, {}), progress, None, local=False)
        out["stats"] = {**scanned["stats"], **out["stats"], "entities": scanned["stats"]["entities"]}
        out["scanSeconds"] = scan_seconds
        out["seconds"] = round(time.monotonic() - start, 1)
        out["usage"] = usage
        results[run["name"]] = out
        print(f"  [{run['name']}] 完成，{out['seconds']} 秒", flush=True)

    base_name = args.baseline or next(iter(results))
    base = names_of(results[base_name]["materials"])
    print("\n| 组 | 秒 | 调用 | 输入 tok | 输出 tok | 事实通过 | 丢弃 | 实体 | 卡片 | 不实用 | 体系 | 剧情段 | 召回(对 " + base_name + ") |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, out in results.items():
        st, u = out["stats"], out["usage"]
        mine = names_of(out["materials"])
        hit = sum(1 for k in base if k in mine)
        recall = f"{hit}/{len(base)}" if base else "-"
        print(f"| {name} | {out['seconds']}（阅读 {out['scanSeconds']}） | {u['calls']} | {u['promptTokens']} | {u['completionTokens']} | "
              f"{st['factsVerified']} | {st['factsUnverified']} | {st['entities']} | {st['cards']} | {st['notUseful']} | "
              f"{st['systems']} | {st['arcs']} | {recall} |")

    top = sorted((m for m in results[base_name]["materials"] if m["category"] != "plot"),
                 key=lambda m: -len(m.get("facts", [])))[:5]
    for m in top:
        key = f"{m['category']}:{_norm_title(m['title'])}"
        print(f"\n==== {m['category']} · {m['title']} ====")
        for name, out in results.items():
            c = names_of(out["materials"]).get(key)
            if not c:
                print(f"[{name}] （没有）")
                continue
            attrs = "；".join(f"{k}：{v}" for k, v in c["attributes"].items())
            print(f"[{name}] {c['summary']}\n    {c.get('detail', '')[:200]}\n    {attrs[:300]}\n    事实 {len(c.get('facts', []))} 条")
    for name, out in results.items():
        arcs = [m for m in out["materials"] if m["category"] == "plot"]
        print(f"\n[{name}] 剧情段：" + "；".join(f"{a['title']}（{a['subtype']}）" for a in arcs[:8]))

    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n完整结果：{args.out}")


if __name__ == "__main__":
    main()
