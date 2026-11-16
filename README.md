# nan_novel · AI 辅助网文创作

从别的小说里**汲取素材**，再用这些素材辅助**构思与写作**的本地优先工具：

- 抓取或上传小说；
- AI 逐章阅读，记下其中的魔物、世界观、角色、物品等设定（每条事实都核对原文），同时拆出每章的钩子、爽点、伏笔；
- 整理成可借鉴的素材卡，同一种东西在不同小说里的写法合并为「共性 + 可选版本」，还可以加工成不带原作专名的「架空版」；
- 从写作参数和一个想法出发，自动规划出设定和全书骨架；
- 构思和写作时，按需检索素材交给 AI。

大模型（DeepSeek 等 OpenAI 兼容接口，或 Anthropic 接口）和本地模型（llama.cpp GGUF / Transformers）都能用。素材检索全程在本机运行，不花 token。

## 主要功能

| 模块 | 说明 |
|---|---|
| 文件管理 | 上传 txt / md / docx / pdf；GBK 小说自动转码，大文件分页预览 |
| 小说抓取 | 单本按目录页抓取；AI 解析站点规律后批量采集书目、筛选、抓取；断点续抓 |
| 小说提取 | 只读原文：一章一次调用、按章节顺序读，记录设定实体和具体事实，附原文依据并由代码核对，默认读两遍补漏；同时出章节卡（一句话、钩子、爽点、伏笔的埋设 / 推进 / 回收），分快速 / 标准 / 深拆三档；暂停 / 继续 / 接着读 / 重读某几章 |
| 提取工作区 | 边提取边看：左边章节、中间原文（核实过的摘抄高亮）、右边本章的实体和章节卡；全书实体视图和实体出场图；合并同一个实体 |
| 整理卡片 | 把实体档案整理成素材卡（详细描述、属性、作者用法、借用提示、量级）、体系卡、剧情段、写法卡、世界观卡、共鸣素材（一组互相牵连的设定：关系图 + 联动规则）；入库前和这本书已有的素材比对，逐条确认 |
| 素材库 | 关键词 / 标签检索；本地向量 + BM25 混合检索 + 交叉编码器重排；按来源书筛选、屏蔽、保留；素材量级（个人 → 神明五级），检索时按故事阶段过滤 |
| 精炼合并 | 找出跨书 / 同书的相似素材，合并为「共性 + 可选版本」，可拆分还原；AI 使用时可让它选一个版本、只用某一版或融合 |
| 架空工作区 | 把原素材加工成能搬到别的小说里用的「架空版」：可移植内核、叙事用途、换世界时替换什么、一定保留什么；代码检查原作专名有没有漏进去；原素材不动 |
| 自动规划 | 新建工作区时走一遍：写作参数 + 灵感（3 个故事灵感选 1 个）→ 设定（世界规则、力量体系、主角，每块可单独重来）→ 全书骨架（卷 × 阶段，再按骨架配配角和元素）→ 写进工作区 |
| 角色卡 | 从传记 / 小说里提取人物内核（性格、价值观、决策规则、说话方式，每条带原文证据），适配到完全不同的世界观，用于写作、规划和一致性检查；辨识度测试；升级后的试聊（情境演绎、心理访谈、防走偏） |
| 灵感墙 | 只给一个念头甚至什么都不给，AI 拆成检索需求、从素材库找素材（本地检索，跨书、可随机探索），组合成几个标明出处的具体思路；可收藏、细化、追问修改，写进工作区的大纲 / 设定 / 构思方向 |
| 书房（写作工作区） | 可扩展的设定编辑器（右侧素材库栏）、AI 构思（书名 / 大纲 / 后续走向）、AI 填写设定、分段生成章节、章节规划、故事账本（伏笔 / 角色状态 / 时间线）、世界书（把设定、人物内核、账本编译成统一的故事知识）、一致性检查 |
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
| 大模型 | OpenAI 兼容 `/chat/completions`（DeepSeek、通义千问、Kimi、OpenAI…）或 Anthropic Messages 接口，JSON 模式，token 用量与费用估算 |
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

## 正在设计

素材提取出来之后怎么用得更好，目前在讨论阶段，还没有实现，记录在 [素材使用方案](docs/素材使用方案.md)：

- **素材树**：作者定主干（如力量体系、剧情走向、写作手法、角色内核），AI 在主干下延伸出枝并把素材挂上去；生成时先匹配枝，再在枝里检索。
- **多个检索方向**：一条素材按「是什么 / 怎么运转 / 代价和限制 / 能起什么作用」分别建向量，按正在生成的内容选方向。
- **写法做成可开关的说明**：把写法类素材整理成写章节时按需挂载、随时可以撤掉的写作说明。
- **检索测试**：先用作者自己的标注比较几种检索做法，再定产品方案。

其他待办见 [`docs/待办.md`](docs/待办.md)。

## 文档

- [`docs/`](docs/README.md)：核心处理逻辑的设计与实现细节
  - [素材流程](docs/素材流程.md)：逐章读、原文依据核对、整理卡片、入库比对、架空版、量级、断点续跑、实测
  - [素材检索](docs/素材检索.md)：向量 + BM25 混合召回、倒数排名融合、重排、多版本召回
  - [精炼合并](docs/精炼合并.md)：相似素材怎么找、合并稿与依据检查、共性 + 可选版本、AI 怎么用多版本素材
  - [跨世界观角色卡](docs/跨世界观角色卡.md)：人物内核提取、适配、写作接入、辨识度测试
  - [试聊](docs/试聊.md)：模式、锚点、走偏检测、反馈
  - [灵感墙](docs/灵感墙.md)：拆需求、本地检索素材、生成带引用的思路，四个出口
  - [自动规划](docs/自动规划.md)：写作参数 + 灵感 → 设定 → 全书骨架，开篇规则与代码检查
  - [世界书](docs/世界书.md)：把工作区的故事知识编译成统一条目，人物局面和定时事件
  - [走向引擎](docs/走向引擎.md)：基于世界书出后续走向，评测方法和实测对比
  - [素材使用方案](docs/素材使用方案.md)：讨论稿，素材怎么检索、怎么融入生成
- [`CLAUDE.md`](CLAUDE.md)：核心规则和文档索引（也是给 AI 编程助手看的项目说明）；接口、表结构等细节在 [`docs/claude/`](docs/claude/README.md)
- [`模型对比测试报告.md`](模型对比测试报告.md)：DeepSeek vs 本地 GGUF vs safetensors 的速度与质量对比

## 参考与致谢

- 小说抓取的整站采集思路参考了 [hahaha108/copyBook](https://github.com/hahaha108/copyBook)，本项目重新实现，没有包含它的代码。如有侵权，通知必删。
- 书房的布局参考了 EasyWriting 的界面设计，没有使用它的代码和图片。
