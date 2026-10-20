"""本地 LoRA 适配器效果验证（走真实 HTTP 接口，不训练）：

  1. 找到适配器可加载的基础模型（matchedBaseId）；没有且给了 --model-path 时先登记该目录（只记路径）
  2. 加载「基础模型 + 适配器」
  3. 定量：同一文本停用 / 启用适配器的 loss 与困惑度（/api/local/inference/evaluate）
       - 风格文本（--style-file，默认取适配器训练任务的 samples.txt 中段）：适配器应明显降低困惑度
       - 对照文本（--control-file，默认内置的现代白话散文）：差距应小得多 —— 说明学到的是该风格而非泛化变化
  4. 定性：同一提示词、同一种子，基础模型 vs 适配器续写（/api/local/inference/compare）
  5. 小说生成链路：建一个使用该适配器的临时工作区 → 加载模型 → 生成一小章，检查章节记录的 adapterId，最后删除工作区
     （--skip-novel 跳过）

用法（python-service 目录下，AI 服务需已启动，代理不影响）：
  .venv/Scripts/python scripts/adapter_eval.py --adapter model-6ba720 --port 8011
      [--model-path "D:/.../Qwen2.5-1.5B-Instruct"] [--style-file x.txt] [--control-file y.txt] [--skip-novel]
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]

CONTROL_TEXT = """\
周末的早晨，我习惯先去楼下的菜市场转一圈。卖菜的阿姨认得我，总会多塞两根葱。她说今年雨水多，青菜长得快，价钱也便宜了些。
我买了一把菠菜、两个西红柿，又在隔壁摊子上称了半斤豆腐。回家的路上经过一家新开的面包店，门口排着队，空气里都是黄油的香味。
其实我并不怎么爱吃面包，可那天还是忍不住买了一个。店员是个刚毕业的小姑娘，说话很快，找零的时候还认真地说了一句"欢迎下次再来"。
回到家，阳光正好照进厨房。我把菜洗干净，放在窗台上晾着，然后泡了一壶茶，坐在阳台上看楼下的孩子们踢球。
他们踢得乱七八糟，球总是滚到花坛里，可每个人都笑得很开心。我忽然想起小时候，也是这样在院子里跑来跑去，一直玩到天黑才被大人喊回家。
那时候的日子好像很慢，一个下午可以很长很长。现在不一样了，工作日忙忙碌碌，一转眼一周就过去了。
所以我格外珍惜这样的周末。不用赶时间，不用看手机，只是安安静静地做一顿饭，读几页书，晚上早点睡。
中午做了西红柿炒蛋和菠菜豆腐汤，味道很普通，但吃得很舒服。饭后我睡了一个短短的午觉，醒来时窗外起了风，云也多了起来。
傍晚下了一场小雨。我站在窗边看雨点打在玻璃上，一道一道往下流。楼下的孩子们早就散了，只剩下一只橘猫躲在车底下，探出脑袋看着外面。
"""

PROMPTS = [
    "汪淼觉得，来找他的这四个人是一个奇怪的组合：两名警察和两名军人，",
    "那天夜里，雷达峰顶的天线突然转向了太阳，",
]


def make_api(port: int):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 不走系统代理

    def call(method, path, body=None, timeout=900):
        req = urllib.request.Request(f"http://localhost:{port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=timeout) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            res = json.loads(e.read() or b"{}")
        if res.get("code") != 0:
            raise SystemExit(f"✗ {method} {path} 失败：{res.get('message') or res}")
        return res["data"]

    return call


def wait_loaded(call, timeout=900):
    start = time.time()
    while time.time() - start < timeout:
        st = call("GET", "/api/local/inference")
        if st["status"] == "loaded":
            return st
        if st["status"] == "error":
            raise SystemExit(f"✗ 加载失败：{st['error']}")
        time.sleep(3)
    raise SystemExit("✗ 加载超时")


def default_style_text(adapter: dict, chars: int) -> str:
    """训练任务 samples.txt 的中段（跳过开头的版权页 / 前言）。"""
    f = SERVICE_ROOT / "models" / "jobs" / (adapter.get("jobId") or "") / "samples.txt"
    if not f.exists():
        raise SystemExit(f"✗ 找不到训练样本 {f}，请用 --style-file 指定目标风格文本")
    text = f.read_text(encoding="utf-8")
    mid = len(text) // 2
    return text[mid:mid + chars]


def show_eval(name: str, r: dict) -> None:
    print(f"  {name}: {r['tokens']} tokens  base loss {r['base']['loss']:.3f} / ppl {r['base']['ppl']:.2f}"
          f"  →  adapter loss {r['adapter']['loss']:.3f} / ppl {r['adapter']['ppl']:.2f}"
          f"  （困惑度 {r['pplChangePct']:+.1f}%）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--model-path", help="适配器没有可加载的基础模型时，登记这个目录")
    ap.add_argument("--style-file")
    ap.add_argument("--control-file")
    ap.add_argument("--chars", type=int, default=6000, help="风格文本取多少字")
    ap.add_argument("--max-new-tokens", type=int, default=160)
    ap.add_argument("--skip-novel", action="store_true")
    args = ap.parse_args()
    call = make_api(args.port)

    print("== 1. 适配器与基础模型")
    adapter = call("GET", f"/api/local/adapters/{args.adapter}")
    if not adapter.get("matchedBaseId") and args.model_path:
        base = call("POST", "/api/local/models/register",
                    {"name": adapter["baseModel"].get("name") or "base", "path": args.model_path})
        print(f"  已登记基础模型 {base['id']} → {base['path']}")
        adapter = call("GET", f"/api/local/adapters/{args.adapter}")
    print(f"  适配器「{adapter['name']}」 compat={adapter['compat']} matchedBaseId={adapter['matchedBaseId']}")
    if not adapter.get("matchedBaseId"):
        raise SystemExit("✗ 没有可加载该适配器的本地基础模型（用 --model-path 登记训练时用的模型目录）")
    base_id = adapter["matchedBaseId"]

    print("== 2. 加载基础模型 + 适配器")
    call("POST", "/api/local/inference/load", {"baseId": base_id, "adapterId": args.adapter, "quantization": "auto"})
    st = wait_loaded(call)
    print(f"  已加载 base={st['baseId']} adapter={st['adapterId']} quant={st['quantization']}")

    print("== 3. 困惑度对比（同一文本，停用 / 启用适配器）")
    style = (Path(args.style_file).read_text(encoding="utf-8")[:args.chars] if args.style_file
             else default_style_text(adapter, args.chars))
    control = Path(args.control_file).read_text(encoding="utf-8") if args.control_file else CONTROL_TEXT
    ev_style = call("POST", "/api/local/inference/evaluate", {"text": style})
    ev_control = call("POST", "/api/local/inference/evaluate", {"text": control})
    show_eval("风格文本", ev_style)
    show_eval("对照文本", ev_control)

    print("== 4. 同种子续写对比（基础模型 vs 适配器）")
    for p in PROMPTS:
        r = call("POST", "/api/local/inference/compare",
                 {"prompt": p, "maxNewTokens": args.max_new_tokens, "temperature": 0.8, "seed": 1234})
        print(f"  提示：{p}")
        print(f"  [基础] {r['base']['text'].strip()[:200]}")
        print(f"  [适配] {r['adapter']['text'].strip()[:200]}")
        print(f"  {'输出相同（适配器可能未生效）' if r['base']['text'] == r['adapter']['text'] else '输出不同'}")

    novel_ok = None
    if not args.skip_novel:
        print("== 5. 小说生成链路（工作区使用适配器）")
        novel = call("POST", "/api/gen/novels", {"title": "适配器验证（临时）", "contextWindow": 8192,
                                                 "model": {"source": "local", "baseId": base_id,
                                                           "adapterId": args.adapter}})
        try:
            call("POST", f"/api/gen/novels/{novel['id']}/model/load")
            wait_loaded(call)
            job = call("POST", f"/api/gen/novels/{novel['id']}/chapters",
                       {"goal": "叶文洁在红岸基地值夜班，第一次收到来自太空的回信。", "title": "回信", "targetChars": 400})
            while job["status"] in ("queued", "running"):
                time.sleep(3)
                job = call("GET", f"/api/gen/jobs/{job['id']}")
            ch = job.get("chapter") or {}
            print(f"  任务 {job['status']} {job.get('error') or ''}")
            print(f"  章节记录的模型：{ch.get('model')}")
            print(f"  调用：{[(c['type'], c['completionTokens']) for c in ch.get('calls', [])]}")
            print(f"  正文前 200 字：{(ch.get('text') or '').strip()[:200]}")
            print(f"  摘要：{ch.get('summary')}")
            novel_ok = job["status"] == "succeeded" and (ch.get("model") or {}).get("adapterId") == args.adapter
        finally:
            call("POST", f"/api/gen/novels/{novel['id']}/delete")

    print("== 结论")
    gap = ev_style["lossDelta"] - ev_control["lossDelta"]
    effective = ev_style["lossDelta"] < -0.05 and gap < -0.05
    print(f"  风格文本 loss 变化 {ev_style['lossDelta']:+.3f}，对照文本 {ev_control['lossDelta']:+.3f}，差 {gap:+.3f}")
    print(f"  {'✓ 适配器生效：显著降低目标风格文本的困惑度，且主要作用于该风格' if effective else '✗ 未观察到明显的风格特异效果'}")
    if novel_ok is not None:
        print(f"  {'✓' if novel_ok else '✗'} 小说生成使用了适配器")
    sys.exit(0 if effective and novel_ok is not False else 1)


if __name__ == "__main__":
    main()
