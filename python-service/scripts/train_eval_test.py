"""P2 训练回归测试（真实 HTTP 接口 + 本地小模型，脚本自己启动测试服务）：

  1. 多章节样本：按章节分组划分验证集，eval_loss 训练前后都有，无交叉，验证集不进训练集；固定提示词续写样例写入 meta.json
  2. 无章节样本：退化为末尾连续片段（有警告）
  3. 验证集不足一个完整块：评估跳过并记录原因，文本并回训练集，适配器照常保存
  4. valRatio = 0：不划分
  5. 取消运行中的训练 / worker 异常退出：状态正确、不留下适配器
  6. /train/defaults 返回档位；请求不传可调参数时使用 "local" 档

只用测试端口和独立目录（不影响日常服务）：
  .venv/Scripts/python scripts/train_eval_test.py --model-path "D:/.../Qwen2.5-1.5B-Instruct" --work-dir models/_test/<空目录>
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs_queue_test import Api, Server, check, results, wait_for, wait_final  # noqa: E402


def chapters(n: int, paras: int = 6) -> str:
    return "\n\n".join(f"第{c}章 标题{c}\n" + "\n".join(
        f"第{c}章第{p}段：风从城墙外吹进来，带着潮湿的泥土气味，巡夜人提着灯慢慢走过长街。" for p in range(1, paras + 1))
        for c in range(1, n + 1))


NO_CHAPTERS = "\n".join(f"第{i}行，没有章节标题的正文，写着雨夜里的旧城、归人和一盏不肯熄灭的灯。" for i in range(1, 160))
SHORT = "\n".join(f"短样本第{i}句，夜雨落在青石巷里。" for i in range(1, 60))


def submit(api: Api, base_id: str, name: str, text: str, **kw) -> dict:
    body = {"baseModelId": base_id, "adapterName": name, "method": "qlora", "sampleText": text, "force": True,
            "maxSteps": 3, **kw}
    code, res = api.call("POST", "/train", body)
    if code != 200:
        raise RuntimeError(f"提交训练失败 {code}: {res}")
    return res["data"]


def meta_of(work: Path, job: dict) -> dict | None:
    p = work / "models" / "adapters" / job["config"]["adapterId"] / "meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--port", type=int, default=8011)
    args = ap.parse_args()
    if args.port in (8021, 8022, 5173):
        sys.exit("不要在日常端口上运行测试")
    work = Path(args.work_dir).resolve()
    if work.exists() and any(work.iterdir()):
        sys.exit(f"工作目录不为空：{work}")
    work.mkdir(parents=True, exist_ok=True)
    server, api = Server(args.port, work), Api(args.port)
    server.start()
    try:
        code, res = api.call("POST", "/models/register", {"name": "test-base", "path": args.model_path})
        if not check("register_base", code == 200, res.get("message", "")):
            return 1
        base_id = res["data"]["id"]
        code, res = api.call("GET", "/train/defaults")
        prof = (res.get("data") or {}).get("profiles", {})
        check("defaults_endpoint", code == 200 and prof.get("remote", {}).get("learningRate") == 1e-4
              and prof.get("local", {}).get("maxSeqLen") == 512, json.dumps(prof.get("remote"), ensure_ascii=False))
        sample_prompt = res["data"]["samplePrompt"]

        # ---- 1 多章节：与前端相同的显式参数
        j1 = submit(api, base_id, "p2-group", chapters(40), epochs=3, learningRate=0.0002, maxSeqLen=128, batchSize=1,
                    gradAccum=1, loraR=16, loraAlpha=32, loraDropout=0.05)
        r1 = wait_final(api, j1["id"])
        m1 = meta_of(work, r1) or {}
        sp, ev, sm = (m1.get("dataset") or {}).get("split") or {}, m1.get("evaluation") or {}, m1.get("sample") or {}
        check("t1_succeeded", r1["status"] == "succeeded" and m1, f"status={r1['status']} error={(r1.get('error') or '')[:300]}")
        check("t1_group_split", sp.get("mode") == "group" and sp.get("valBlocks", 0) >= 1 and sp.get("groupsTotal") == 40,
              f"mode={sp.get('mode')} groups={sp.get('groupsTotal')} val={sp.get('val')} valBlocks={sp.get('valBlocks')}")
        check("t1_no_overlap", sp.get("groupOverlap") == 0 and sp.get("paragraphOverlap") == 0 and sp.get("blockOverlap") == 0,
              f"group={sp.get('groupOverlap')} para={sp.get('paragraphOverlap')} block={sp.get('blockOverlap')}")
        check("t1_val_not_trained", ev.get("trainDatasetSize") == m1.get("dataset", {}).get("blocks") == sp.get("trainBlocks"),
              f"trainDataset={ev.get('trainDatasetSize')} trainBlocks={sp.get('trainBlocks')}")
        check("t1_eval_loss", ev.get("status") == "ok" and finite(ev.get("evalLossBefore")) and finite(ev.get("evalLossAfter")),
              f"before={ev.get('evalLossBefore')} after={ev.get('evalLossAfter')}")
        check("t1_sample", sm.get("status") == "ok" and sm.get("prompt") == sample_prompt and sm.get("text")
              and sm.get("baseText") and sm.get("params", {}).get("seed") is not None and sm.get("model"),
              f"text={sm.get('text', '')[:40]!r}")
        check("t1_params_recorded", m1.get("training", {}).get("valRatio") == 0.05 and m1.get("training", {}).get("steps") == 3)

        # ---- 2 无章节：末尾片段；可调参数不传（使用 local 档）
        j2 = submit(api, base_id, "p2-tail", NO_CHAPTERS, maxSeqLen=128)
        r2 = wait_final(api, j2["id"])
        m2 = meta_of(work, r2) or {}
        sp2, ev2 = m2.get("dataset", {}).get("split", {}), m2.get("evaluation", {})
        check("t2_tail_split", r2["status"] == "succeeded" and sp2.get("mode") == "tail" and sp2.get("warnings")
              and ev2.get("status") == "ok" and sp2.get("paragraphOverlap") == 0,
              f"status={r2['status']} mode={sp2.get('mode')} eval={ev2.get('status')} error={(r2.get('error') or '')[:200]}")
        check("t2_local_profile", r2["config"]["learningRate"] == 2e-4 and r2["config"]["epochs"] == 3
              and r2["config"]["paramProfile"] == "local")

        # ---- 3 验证集不足一个完整块
        j3 = submit(api, base_id, "p2-none", SHORT, maxSeqLen=512)
        r3 = wait_final(api, j3["id"])
        m3 = meta_of(work, r3) or {}
        sp3, ev3 = m3.get("dataset", {}).get("split", {}), m3.get("evaluation", {})
        check("t3_none_recorded", r3["status"] == "succeeded" and sp3.get("mode") == "none" and ev3.get("status") == "skipped"
              and "不足一个完整块" in (ev3.get("reason") or "") and "evalLossAfter" not in ev3
              and m3.get("sample", {}).get("status") == "ok",
              f"status={r3['status']} mode={sp3.get('mode')} reason={ev3.get('reason')}")

        # ---- 4 valRatio = 0
        j4 = submit(api, base_id, "p2-off", chapters(10), maxSeqLen=128, valRatio=0)
        r4 = wait_final(api, j4["id"])
        sp4 = (meta_of(work, r4) or {}).get("dataset", {}).get("split", {})
        check("t4_disabled", r4["status"] == "succeeded" and sp4.get("mode") == "disabled" and sp4.get("valBlocks") == 0,
              f"mode={sp4.get('mode')}")

        # ---- 5a 取消
        j5 = submit(api, base_id, "p2-cancel", chapters(40), maxSeqLen=128, maxSteps=60, gradAccum=1)
        wait_for(lambda: ((api.job(j5["id"]).get("progress") or {}).get("step") or 0) >= 1, 300)
        api.call("POST", f"/jobs/{j5['id']}/cancel")
        r5 = wait_final(api, j5["id"], 150)
        check("t5_cancel", r5["status"] == "cancelled" and meta_of(work, r5) is None
              and not (work / "models" / "adapters" / (r5["config"]["adapterId"] + ".partial")).exists(),
              f"status={r5['status']}")

        # ---- 5b worker 异常退出
        j6 = submit(api, base_id, "p2-crash", chapters(40), maxSeqLen=128, maxSteps=60, gradAccum=1)
        run6 = wait_for(lambda: ((j := api.job(j6["id"])).get("progress") or {}).get("step", 0) >= 1 and j, 300)
        if run6:
            subprocess.run(["taskkill", "/PID", str(run6["pid"]), "/T", "/F"], capture_output=True)
        r6 = wait_final(api, j6["id"], 60)
        check("t6_crash_failed", r6["status"] == "failed" and "异常退出" in (r6.get("error") or "")
              and meta_of(work, r6) is None, f"status={r6['status']} error={(r6.get('error') or '')[:60]}")
    finally:
        try:
            server.kill()
        except Exception as e:  # noqa: BLE001
            print("停止测试服务失败：", e)
    failed = [n for n, ok, _ in results if not ok]
    print("\nSUMMARY", f"{len(results) - len(failed)}/{len(results)} passed", "FAILED:" if failed else "", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
