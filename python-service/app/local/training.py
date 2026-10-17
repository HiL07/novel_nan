"""LoRA / QLoRA 风格微调（在 worker 子进程中运行，结束即释放显存与内存）。

做法：把用户的写作样本拼接后按 maxSeqLen 切成定长块，做因果语言模型续写训练（continued pretraining），
让模型学习用词、句式、节奏等风格；只训练 LoRA 参数，产出的适配器保存到 models/adapters/<id>/。
"""
import math
from pathlib import Path
import platform
import shutil
import time

from . import hardware, jobfiles, registry
from .inference import load_model_and_tokenizer

GB = hardware.GB


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_blocks(tokenizer, text: str, seq_len: int) -> tuple[list[list[int]], int]:
    """整段分词后切成 seq_len 的定长块；不足一块时整段作为一块。返回 (blocks, 总 token 数)。"""
    ids = tokenizer(text, add_special_tokens=False)["input_ids"]
    if tokenizer.eos_token_id is not None:
        ids.append(tokenizer.eos_token_id)
    blocks = [ids[i:i + seq_len] for i in range(0, len(ids) - seq_len + 1, seq_len)]
    if not blocks:
        blocks = [ids]
    return blocks, len(ids)


def run(job: dict) -> dict:
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import DataCollatorForLanguageModeling, Trainer, TrainerCallback, TrainingArguments

    job_id, cfg = job["id"], job["config"]
    base = cfg["baseModel"]
    quant = "4bit" if cfg["method"] == "qlora" else "none"
    tinfo = hardware.torch_info()
    if not tinfo["cuda"]:
        raise RuntimeError("未检测到可用的 CUDA GPU，本地训练需要 NVIDIA GPU")
    if registry.config_hash(Path(base["path"])) != base["configHash"]:
        raise RuntimeError("基础模型的 config.json 与登记时不同，请重新登记该模型")

    samples = (jobfiles.job_dir(job_id) / "samples.txt").read_text(encoding="utf-8")
    _log(f"基础模型：{base['name']}（{base['path']}）")
    _log(f"方法：{cfg['method'].upper()}  量化：{quant}  样本 {len(samples)} 字")

    torch.manual_seed(cfg["seed"])
    torch.cuda.reset_peak_memory_stats()
    t0 = time.monotonic()
    model, tokenizer = load_model_and_tokenizer(base["path"], quant)
    _log(f"模型加载完成，用时 {time.monotonic() - t0:.1f}s，显存 {torch.cuda.memory_allocated() / GB:.2f} GB")

    blocks, n_tokens = build_blocks(tokenizer, samples, cfg["maxSeqLen"])
    _log(f"样本切分：{n_tokens} tokens → {len(blocks)} 块（每块 ≤ {cfg['maxSeqLen']} tokens）")

    gc_kwargs = {"use_reentrant": False}
    if quant == "4bit":
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                                gradient_checkpointing_kwargs=gc_kwargs)
    else:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs=gc_kwargs)
        model.enable_input_require_grads()
    lora_cfg = LoraConfig(r=cfg["loraR"], lora_alpha=cfg["loraAlpha"], lora_dropout=cfg["loraDropout"],
                          target_modules="all-linear", bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora_cfg)
    trainable, total = model.get_nb_trainable_parameters()
    _log(f"LoRA 可训练参数 {trainable / 1e6:.2f}M / 总参数 {total / 1e6:.0f}M（{trainable / total:.2%}）")

    steps_per_epoch = math.ceil(len(blocks) / (cfg["batchSize"] * cfg["gradAccum"]))
    max_steps = cfg["maxSteps"] or steps_per_epoch * cfg["epochs"]
    _log(f"训练步数：{max_steps}（每轮 {steps_per_epoch} 步，batch {cfg['batchSize']} × 累积 {cfg['gradAccum']}）")

    progress = {"step": 0, "maxSteps": max_steps, "epoch": 0, "loss": None, "learningRate": None,
                "elapsed": 0, "eta": None, "history": []}
    jobfiles.write_progress(job_id, progress)
    train_start = time.monotonic()

    class ProgressCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            if not logs or "loss" not in logs:
                return
            elapsed = time.monotonic() - train_start
            step = state.global_step
            progress.update(step=step, epoch=round(state.epoch or 0, 2), loss=round(logs["loss"], 4),
                            learningRate=logs.get("learning_rate"), elapsed=round(elapsed),
                            eta=round(elapsed / step * (max_steps - step)) if step else None)
            progress["history"].append({"step": step, "loss": round(logs["loss"], 4)})
            jobfiles.write_progress(job_id, progress)
            _log(f"step {step}/{max_steps}  loss {logs['loss']:.4f}  lr {logs.get('learning_rate', 0):.2e}")

        def on_step_end(self, args, state, control, **kwargs):
            if jobfiles.cancel_requested(job_id):
                _log("收到取消请求，正在停止训练…")
                control.should_training_stop = True

    args = TrainingArguments(
        output_dir=str(jobfiles.job_dir(job_id) / "trainer"),
        per_device_train_batch_size=cfg["batchSize"],
        gradient_accumulation_steps=cfg["gradAccum"],
        max_steps=max_steps,
        learning_rate=cfg["learningRate"],
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=1,
        save_strategy="no",
        report_to=[],
        bf16=tinfo["bf16"],
        fp16=not tinfo["bf16"],
        optim="paged_adamw_8bit" if quant == "4bit" else "adamw_torch",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs=gc_kwargs,
        dataloader_num_workers=0,
        remove_unused_columns=False,
        disable_tqdm=True,
        seed=cfg["seed"],
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=[{"input_ids": b} for b in blocks],
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
        callbacks=[ProgressCallback()],
    )
    out = trainer.train()
    if jobfiles.cancel_requested(job_id):
        _log("训练已取消，未保存适配器")
        return {"cancelled": True}

    peak = torch.cuda.max_memory_allocated() / GB
    _log(f"训练完成：{out.global_step} 步，用时 {out.metrics.get('train_runtime', 0):.0f}s，显存峰值 {peak:.2f} GB")

    # 先存到临时目录，全部成功后再改名，避免留下半个适配器
    adapter_id = cfg["adapterId"]
    final_dir = registry.adapter_dir(adapter_id)
    tmp_dir = final_dir.with_name(adapter_id + ".partial")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    model.save_pretrained(str(tmp_dir))
    tokenizer.save_pretrained(str(tmp_dir))

    sample = _sample_generation(model, tokenizer, samples)
    from importlib.metadata import version

    meta = {
        "id": adapter_id,
        "name": cfg["adapterName"],
        "source": "local",
        "createdAt": jobfiles.now(),
        "jobId": job_id,
        "baseModel": {k: base.get(k) for k in ("id", "name", "path", "configHash", "modelType", "architecture",
                                               "numParams")},
        "method": cfg["method"],
        "quantization": quant,
        "training": {k: cfg[k] for k in ("loraR", "loraAlpha", "loraDropout", "maxSeqLen", "epochs",
                                         "learningRate", "batchSize", "gradAccum", "seed")}
                    | {"steps": out.global_step, "targetModules": "all-linear"},
        "dataset": {"chars": len(samples), "tokens": n_tokens, "blocks": len(blocks),
                    "sources": cfg.get("sampleSources", [])},
        "metrics": {"finalLoss": progress["loss"], "trainRuntime": round(out.metrics.get("train_runtime", 0), 1),
                    "peakVramGB": round(peak, 2)},
        "sample": sample,
        "env": {"torch": torch.__version__, "transformers": version("transformers"), "peft": version("peft"),
                "gpu": torch.cuda.get_device_name(0), "python": platform.python_version()},
    }
    registry._write_json(tmp_dir / "meta.json", meta)
    if final_dir.exists():
        shutil.rmtree(final_dir)
    tmp_dir.rename(final_dir)
    _log(f"适配器已保存：{final_dir}")
    return {"adapterId": adapter_id}


def _sample_generation(model, tokenizer, samples: str) -> dict:
    """训练后用样本开头做一次续写，便于直观对比风格。失败不影响训练结果。"""
    import torch

    prompt = samples.strip()[:60]
    try:
        model.eval()
        model.config.use_cache = True
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=120, do_sample=True, temperature=0.8, top_p=0.9,
                                 repetition_penalty=1.1, pad_token_id=tokenizer.pad_token_id)
        text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        _log(f"续写示例：{prompt} → {text[:80]}…")
        return {"prompt": prompt, "text": text}
    except Exception as e:  # noqa: BLE001
        _log(f"续写示例失败（不影响适配器）：{e}")
        return {"prompt": prompt, "text": "", "error": str(e)}
