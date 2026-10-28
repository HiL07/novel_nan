# nan_novel · AI 辅助网文创作

从别的小说里**汲取素材**，再用这些素材辅助**构思与写作**的本地优先工具：

- 抓取或上传小说；
- AI 逐段阅读，记下其中的魔物、世界观、角色、物品等设定（每条事实都核对原文）；
- 整理成可借鉴的素材卡，同一种东西在不同小说里的写法合并为「共性 + 可选版本」；
- 构思和写作时，按需检索素材交给 AI。

大模型（DeepSeek 等 OpenAI 兼容接口）和本地模型（llama.cpp GGUF / Transformers）都能用。素材检索全程在本机运行，不花 token。

## 主要功能

| 模块 | 说明 |
|---|---|
| 文件管理 | 上传 txt / md / docx / pdf；GBK 小说自动转码，大文件分页预览 |
| 小说抓取 | 单本按目录页抓取；AI 解析站点规律后批量采集书目、筛选、抓取；断点续抓 |
| 小说提取 | 只读原文：逐段记录设定实体和具体事实，附原文依据并由代码核对，可读两遍补漏；暂停 / 继续 / 断点续跑 |
| 整理卡片 | 把实体档案整理成素材卡（详细描述、属性、作者用法、借用提示）、体系卡、剧情骨架，逐条确认后进素材库 |
| 素材库 | 关键词 / 标签检索；本地向量 + BM25 混合检索 + 交叉编码器重排；按来源书筛选、屏蔽、保留 |
| 精炼合并 | 找出跨书 / 同书的相似素材，合并为「共性 + 可选版本」，可拆分还原；AI 使用时可让它选一个版本、只用某一版或融合 |
| 写作工作区 | 可扩展的设定编辑器、AI 构思（书名 / 大纲 / 走向）、AI 填写设定、分段生成章节、章节规划、故事账本（伏笔 / 角色状态 / 时间线）、一致性检查 |
| 本地模型 | 模型下载 / 登记、显存估算、推理、LoRA / QLoRA 文风微调、困惑度评估；llama.cpp（GGUF）管理 |

## 架构

```
浏览器（Vue 3 + Element Plus，:5173）
        │ HTTP
        ▼
Java 后端（Spring Boot，:8022）── SQLite（data/nan_novel.db，只存元数据）+ data/ 下的文件
        │ HTTP
        ▼
Python AI 服务（FastAPI，:8021）
        ├─► OpenAI 兼容大模型（默认 DeepSeek，可换任意兼容接口）
        ├─► llama.cpp（GGUF，本机）
        ├─► Transformers + PEFT（本机 GPU 推理 / LoRA·QLoRA 训练）
        └─► bge 向量模型 + bge 重排模型 + jieba BM25（素材检索，本机）
```

Java 是文件和元数据的唯一存储方；Python 只做 AI 相关的计算，不保存 API Key。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3.4（`<script setup>`）、Vite 5、Vue Router 4、Element Plus 2.7、Axios |
| 后端 | Java 17、Spring Boot 3.2、MyBatis-Plus 3.5、SQLite（sqlite-jdbc，WAL）、Lombok、Maven |
| AI 服务 | Python 3.10+、FastAPI、Uvicorn、Pydantic v2、httpx、python-docx、pypdf、lxml |
| 大模型 | OpenAI 兼容 `/chat/completions`（DeepSeek、通义千问、Kimi、OpenAI…），JSON 模式，token 用量与费用估算 |
| 本地推理 | llama.cpp `llama-server`（GGUF，由 AI 服务启停）、PyTorch 2.6（CUDA 12.4）+ Transformers |
| 微调 | PEFT LoRA / QLoRA（bitsandbytes nf4 + 双重量化）、accelerate、paged AdamW 8bit |
| 检索 | `BAAI/bge-small-zh-v1.5` 向量、`BAAI/bge-reranker-v2-m3` 交叉编码器重排、jieba + BM25、倒数排名融合 |
| 抓取 | httpx + lxml（XPath 规则 + 启发式解析）、robots.txt、限速、AI 学习站点规律 |

## 快速开始（Windows）

环境：JDK 17、Maven、Node.js、Python 3.10+；不需要数据库服务（SQLite 首次启动自动建库）。本地模型、微调还需要 NVIDIA GPU 和 CUDA 版 PyTorch，见 `python-service/requirements-local.txt` 开头的说明。

```bash
# Python AI 服务
cd python-service
py -3.10 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --port 8021

# Java 后端（另开窗口）
cd backend
mvn spring-boot:run

# 前端（另开窗口）
cd frontend
npm install
npm run dev     # http://localhost:5173
```

也可以用根目录的 `start.bat` 一键启动三个服务（先改好文件开头的 JDK / Maven / Node 路径）。
大模型的 API Key 填在页面的「模型配置」里，或者写进 `backend/application-secret.yml`（不进版本库）。
Docker 部署见 [`docker/README-Docker.md`](docker/README-Docker.md)。

## 文档

- [`docs/`](docs/README.md)：核心处理逻辑的设计与实现细节
  - [素材流程](docs/素材流程.md)：只读原文记事实、原文依据核对、整理卡片、断点续跑、本地 GGUF 实测
  - [素材检索](docs/素材检索.md)：向量 + BM25 混合召回、倒数排名融合、重排、多版本召回
  - [精炼合并](docs/精炼合并.md)：相似素材怎么找、合并稿与依据检查、共性 + 可选版本、AI 怎么用多版本素材
- [`CLAUDE.md`](CLAUDE.md)：完整的接口、表结构、目录约定和开发规范（也是给 AI 编程助手看的项目说明）
- [`模型对比测试报告.md`](模型对比测试报告.md)：DeepSeek vs 本地 GGUF vs safetensors 的速度与质量对比
