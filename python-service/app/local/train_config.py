"""训练参数的唯一定义处：默认值档位（profile）、验证集划分、固定续写样例。

- "local"：本机训练（8GB 显存的保守默认值，与之前前端 / API 的默认值一致，保证本地行为不变）
- "remote"：远程 GPU 正式训练的初始配置（7B QLoRA，已在 RTX 4080 SUPER 32GB 上做过 seq 2048 / batch 1 的 20 步校准）
请求中显式给出的字段覆盖档位默认值；环境变量 TRAIN_DEFAULTS_OVERRIDE（JSON，如 '{"remote": {"learningRate": 5e-5}}'）
可在不改代码的情况下调整档位。
"""
import json
import os

PROFILES: dict[str, dict] = {
    "local": {"learningRate": 2e-4, "epochs": 3, "maxSeqLen": 512, "batchSize": 1, "gradAccum": 4,
              "loraR": 16, "loraAlpha": 32, "loraDropout": 0.05, "valRatio": 0.05},
    "remote": {"learningRate": 1e-4, "epochs": 2, "maxSeqLen": 2048, "batchSize": 1, "gradAccum": 4,
               "loraR": 16, "loraAlpha": 32, "loraDropout": 0.05, "valRatio": 0.05},
}

_override = os.getenv("TRAIN_DEFAULTS_OVERRIDE")
if _override:
    for _name, _vals in json.loads(_override).items():
        PROFILES.setdefault(_name, {}).update({k: v for k, v in _vals.items() if k in PROFILES["local"]})

TUNABLE_KEYS = tuple(PROFILES["local"])

# 验证集：按来源 / 章节分组后整组划入验证集，避免相邻文本同时出现在训练集与验证集
VAL_MIN_GROUPS = 2           # 少于这么多组时不能按组划分，退化为「末尾连续片段」
VAL_MAX_OVERSHOOT = 2.0      # 选入验证集的分组总量最多为目标比例的这么多倍（避免一个超长章节吞掉大半数据）

# 训练结束后的固定续写样例（同一提示词 + 固定种子，便于不同适配器之间对比）
SAMPLE_PROMPT = "夜色渐深，城门外传来一阵急促的马蹄声。"
SAMPLE_PARAMS = {"maxNewTokens": 200, "temperature": 0.8, "topP": 0.9, "repetitionPenalty": 1.1, "seed": 1234,
                 "useChatTemplate": False}


def defaults(profile: str = "local") -> dict:
    if profile not in PROFILES:
        raise ValueError(f"未知的训练参数档位：{profile}")
    return dict(PROFILES[profile])


def resolve(profile: str, given: dict) -> dict:
    """档位默认值 + 请求中显式给出（非 None）的字段。"""
    out = defaults(profile)
    out.update({k: v for k, v in given.items() if k in TUNABLE_KEYS and v is not None})
    return out
