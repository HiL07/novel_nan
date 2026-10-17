"""本地模型端到端冒烟测试（走真实 HTTP 接口）：

  1. 登记基础模型（已登记则复用）
  2. 加载基础模型并生成一段文字
  3. 用写作样本启动一个短训练（默认 30 步 QLoRA），等待完成
  4. 加载保存的适配器并生成文字，与第 2 步对比

用法（python-service 目录下，AI 服务需已启动）：
  .venv/Scripts/python scripts/local_e2e.py --model-path "D:/.../Qwen2.5-1.5B-Instruct" [--port 8011]
      [--samples my_writing.txt] [--steps 30] [--method qlora|lora]
不传 --samples 时使用内置的一小段示例文字（仅用于验证流程，学不到什么风格）。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEMO_SAMPLES = """\
夜雨落在青石巷里，一声，又一声。灯是旧的，人也是旧的。
老陈推开铺子的木门，门轴吱呀一响，像是替他叹了口气。他不说话，只把伞靠在墙角，任水顺着伞骨往下淌，淌成一小摊，映着昏黄的灯。
“还开着？”门外有人问。
“开着。”老陈说，“雨天，总有人要回来。”
来人是个年轻人，肩头湿透，眼神却亮。他在柜台前站定，掏出一枚铜钱，搁下，又推了推。铜钱很轻，落在木头上，几乎没有声响。
老陈看了很久。久到檐下的雨停了一阵，又下起来。
“十年了。”他说。
“十年了。”年轻人说。
两个人便都笑了。笑得很短，像是怕惊动了什么。
巷子尽头有狗叫，叫了两声，也就不叫了。夜还长，雨也还长，可有些话，一句就够。
第二天清早，巷口卖豆浆的王婶说，昨夜看见铺子的灯一直亮着，亮到天快白了才熄。她说这话的时候，锅里的豆浆正翻着白花，咕嘟咕嘟，像是也在跟着点头。
没人知道那个年轻人去了哪里。有人说往北，有人说往南。老陈不说。老陈只是照旧开门，照旧把伞靠在墙角，照旧在雨天里等。
等什么呢？他自己大概也说不清。只是每到落雨，他便把那枚铜钱拿出来，放在柜台上，推一推，再收回去。
铜钱很轻。轻得像一句话。
"""


def make_api(port: int):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 不走系统代理
    base = f"http://localhost:{port}/api/local"

    def call(method, path, body=None, timeout=600):
        req = urllib.request.Request(base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=timeout) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            res = json.loads(e.read() or b"{}")
        if res.get("code") != 0:
            raise SystemExit(f"✗ {method} {path} 失败：{res.get('message')}")
        return res["data"]

    return call


def wait_loaded(call, timeout=900):
    start = time.time()
    while time.time() - start < timeout:
        st = call("GET", "/inference")
        if st["status"] == "loaded":
            return st
        if st["status"] == "error":
            raise SystemExit(f"✗ 模型加载失败：{st['error']}")
        time.sleep(3)
    raise SystemExit("✗ 模型加载超时")


def gen(call, prompt, n=120):
    r = call("POST", "/inference/generate", {"prompt": prompt, "maxNewTokens": n, "temperature": 0.8})
    print(f"  ({r['newTokens']} tokens, {r['seconds']}s, {r['tokensPerSecond']} tok/s)")
    print("  " + (prompt + r["text"]).replace("\n", "\n  "))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--port", type=int, default=8021)
    ap.add_argument("--samples", help="UTF-8 文本文件，你自己的写作样本")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--method", choices=["qlora", "lora"], default="qlora")
    ap.add_argument("--prompt", default="夜雨落在青石巷里，")
    args = ap.parse_args()
    call = make_api(args.port)

    sysinfo = call("GET", "/system")
    print(f"GPU：{sysinfo['gpu']}\n内存：{sysinfo['ram']}\n依赖：{sysinfo['deps']['versions']}")
    if not sysinfo["deps"]["ready"]:
        raise SystemExit("✗ 未安装本地模型依赖，见 requirements-local.txt")

    print("\n[1] 登记基础模型")
    norm = lambda p: p.replace("\\", "/").rstrip("/").lower()
    model = next((m for m in call("GET", "/models") if norm(m["path"]) == norm(args.model_path)), None)
    if model is None:
        model = call("POST", "/models/register", {"name": args.name or args.model_path.rstrip("/\\").split("/")[-1].split("\\")[-1],
                                                  "path": args.model_path})
        print(f"  已登记：{model['name']}（{model['id']}）")
    else:
        print(f"  已存在：{model['name']}（{model['id']}）")

    print("\n[2] 加载基础模型并生成")
    t = time.time()
    call("POST", "/inference/load", {"baseId": model["id"]})
    st = wait_loaded(call)
    print(f"  加载完成 {time.time() - t:.0f}s，量化 {st['quantization']}，显存 {st.get('vramAllocatedGB')} GB")
    gen(call, args.prompt)

    print("\n[3] 启动风格微调")
    samples = open(args.samples, encoding="utf-8").read() if args.samples else DEMO_SAMPLES * 3
    job = call("POST", "/train", {"baseModelId": model["id"], "adapterName": f"e2e-{time.strftime('%H%M%S')}",
                                  "method": args.method, "sampleText": samples, "maxSteps": args.steps,
                                  "maxSeqLen": 256, "gradAccum": 1, "force": True})
    print(f"  任务 {job['id']}（推理模型已自动卸载以释放显存）")
    last = None
    while True:
        job = call("GET", f"/jobs/{job['id']}")
        p = job.get("progress") or {}
        line = f"  {job['status']} step {p.get('step', 0)}/{p.get('maxSteps', '?')} loss {p.get('loss')}"
        if line != last:
            print(line, flush=True)
            last = line
        if job["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(5)
    if job["status"] != "succeeded":
        print(call("GET", f"/jobs/{job['id']}/log", None)["log"][-3000:])
        raise SystemExit(f"✗ 训练{job['status']}：{job.get('error')}")
    adapter = call("GET", f"/adapters/{job['result']['adapterId']}")
    print(f"  适配器：{adapter['name']}（{adapter['id']}），loss {adapter['metrics']['finalLoss']}，"
          f"显存峰值 {adapter['metrics']['peakVramGB']} GB，基础模型匹配：{adapter['compat']}")

    print("\n[4] 加载适配器并生成")
    call("POST", "/inference/load", {"baseId": model["id"], "adapterId": adapter["id"]})
    wait_loaded(call)
    gen(call, args.prompt)
    call("POST", "/inference/unload")
    print("\n✓ 端到端流程通过")


if __name__ == "__main__":
    sys.exit(main())
