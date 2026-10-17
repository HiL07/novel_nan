# nan_novel Docker 部署指南 / Docker Deployment Guide

本文档说明如何用 Docker / Docker Compose 将本项目（Vue3 前端 + Spring Boot 文件管理后端 + FastAPI AI 服务 + MySQL）交付到任意电脑或服务器运行。

This guide covers delivering the stack (Vue3 + Spring Boot + FastAPI + MySQL) to any machine or server with Docker.

---

## 1. 架构与端口 / Architecture & Ports

| 容器 Container | 镜像 Image | 容器内端口 Port | 说明 Purpose |
|---|---|---|---|
| `frontend` | `nan-novel-frontend` (nginx) | 80 | 托管 Vue 静态文件，并反代 `/java/` → 后端、`/ai/` → Python 服务 / Serves the SPA and reverse-proxies both APIs |
| `backend` | `nan-novel-backend` | 8022 | Spring Boot 文件管理后端（系统主服务） / Spring Boot file-management service |
| `python` | `nan-novel-python` | 8021 | FastAPI：文本提取/分析；依赖用 uv 安装，不含 GPU/CUDA / FastAPI extraction service; deps installed by uv, no GPU/CUDA |
| `mysql` | `mysql:8.0` | 3306 | 数据库（库名 `test10000`，表由后端启动时自动创建） / Database; tables auto-created by the backend |

```
浏览器 Browser
   │  http://<主机IP>:8080
   ▼
nginx (frontend 容器)
   ├── /java/api/...  ──► backend:8022/api/...   ──► mysql:3306
   └── /ai/api/...    ──► python:8021/api/...
                              │  按 fileId 拉取源文件 / fetches files by id
                              └──────────────────────► backend:8022
```

默认只有两个端口发布到宿主机：**8080（Web 入口）** 和 **3307（MySQL，可关闭）**。后端 8022、Python 8021 仅在 Docker 内部网络可达。

By default only **8080 (web)** and **3307 (MySQL, optional)** are published to the host.

---

## 2. 环境要求 / Requirements

- Docker Engine **24+**（含 Compose 插件 `docker compose`）。
- Windows / macOS：安装 **Docker Desktop**（Windows 使用 WSL2 后端）。
- Linux：`docker` + `docker-compose-plugin`（`docker compose version` 能输出版本即可）。
- 内存建议 ≥ 4 GB；磁盘 ≥ 5 GB（镜像 + MySQL + 上传文件）。
- 需要联网拉取基础镜像与依赖（离线交付见第 7 节）。
- 无需显卡、无需安装 CUDA / NVIDIA Container Toolkit：容器内只包含 JDK、Node 构建产物与 Python 运行依赖。

Requires Docker 24+ with the Compose plugin, ~4GB RAM and ~5GB disk. No GPU, CUDA or NVIDIA Container Toolkit is needed — images only contain the JDK, the built frontend, and Python runtime dependencies.

```powershell
# 验证安装 / verify
docker --version
docker compose version
```

---

## 3. 配置环境变量 / Configuration

所有部署文件都在项目根目录的 `docker/` 内，**不需要改动任何业务代码或原配置文件**。

All Docker files live in the `docker/` folder; no source/config changes are required.

```powershell
cd docker
copy .env.example .env       # Windows
# cp .env.example .env       # Linux / macOS
```

编辑 `.env`（Change it / 按需修改）：

| 变量 Variable | 含义 Meaning | 默认 Default |
|---|---|---|
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码（**必须改**） / root password (CHANGE) | `change-me-...` |
| `MYSQL_DATABASE` | 数据库名 / database name | `test10000` |
| `MYSQL_PORT` | MySQL 宿主机端口（避免与本机 3306 冲突） / host port | `3307` |
| `FRONTEND_PORT` | Web 入口端口 / web entry port | `8080` |
| `DEEPSEEK_API_KEY` | 可选默认远程模型 Key，留空则在页面配置 / optional default LLM key | 空 empty |

敏感信息只存在于 `.env` 与数据库中，不写入镜像、不提交 Git（`.env` 已在 `.gitignore`）。

Secrets live only in `.env` and the database — never in images or Git.

---

## 4. 构建、启动、停止、更新 / Build · Start · Stop · Update

以下命令均在 `docker/` 目录内执行。Run all commands from the `docker/` directory.

```powershell
# 首次：构建并后台启动（约 5~15 分钟，取决于网络）
# First run: build and start in the background
docker compose up -d --build

# 查看状态（STATUS 变为 healthy 即就绪）
# Check status
docker compose ps

# 实时日志 / follow logs
docker compose logs -f
docker compose logs -f backend      # 单个服务 / one service

# 停止（保留数据与镜像） / stop (keeps data and images)
docker compose stop

# 停止并删除容器（数据卷保留，数据不丢） / remove containers (volumes kept)
docker compose down

# 更新代码后重新构建并启动 / rebuild after updating code
docker compose up -d --build
```

启动后访问 / Open: <http://localhost:8080>（服务器用 `http://服务器IP:8080`）。

首次启动时后端会自动连接 MySQL 并执行建表脚本（`CREATE TABLE IF NOT EXISTS`，可安全重复执行，不会删数据）。模型 API Key 在页面「AI 模型配置」中填写并验证。

On first start the backend auto-creates tables. Configure the remote LLM key in the web UI (AI 模型配置).

---

## 5. 健康检查与排错 / Health Checks & Troubleshooting

```powershell
docker compose ps                 # 健康状态 / health summary
docker compose logs --tail=200 backend
docker compose logs --tail=200 python
docker compose logs --tail=200 mysql
```

| 现象 Symptom | 排查方向 What to check |
|---|---|
| `frontend` 起不来 / unhealthy | `docker compose logs frontend`；多为 8080 被占用，改 `.env` 的 `FRONTEND_PORT` / port 8080 in use → change `FRONTEND_PORT` |
| `backend` 反复重启 | 多半是 MySQL 尚未就绪或密码不一致：检查 `.env` 与 mysql 日志 / MySQL not ready or password mismatch |
| 页面打开但接口报错 | 确认浏览器访问的是 8080（同源走 nginx）；`docker compose logs frontend backend` / use port 8080 so requests go through nginx |
| 上传失败/413 | nginx 已放行 50MB，与后端一致；勿在前面再加限制更小的代理 / nginx allows 50MB; don't put a stricter proxy in front |
| Python 提取任务失败 | `logs python`：看是否连不到 `backend:8022`（同网络默认互通）或文件 id 不存在 / check network or file id |
| 「Python 环境」页为空 | **正常现象**：该页检测的是宿主机 Python（开发模式用）；容器化后 AI 服务已独立运行，无需在此检测 / expected: that page probes the host Python for the dev workflow; the AI service runs as its own container |
| 「本地模型」页提示依赖未安装 | **正常现象**：容器内只安装文本提取依赖，不含 torch/CUDA；本机推理与 QLoRA 微调请在宿主机的 Python 环境中进行 / expected: the image ships extraction deps only (no torch/CUDA); run local inference/QLoRA on the host Python env |
| MySQL 端口 3307 连不上 | 默认仅 Web 8080 必需；确认 `.env` 的 `MYSQL_PORT` 未被占用、防火墙已放行 / check port conflicts and firewall |

直接验证内部链路 / Verify the internal chain:

```powershell
# 经 nginx 调 Java 与 Python（应返回 {"code":0,...}）
curl http://localhost:8080/java/api/file/list
curl http://localhost:8080/ai/api/health
```

Windows 没有 curl 时可用 PowerShell：

```powershell
Invoke-WebRequest http://localhost:8080/ai/api/health | Select-Object -Expand Content
```

---

## 6. MySQL：初始化、持久化、备份、恢复 / MySQL: Init, Persistence, Backup, Restore

**初始化 / Init**：`mysql` 容器首次启动时自动创建 `test10000` 库；后端首次启动自动建表。无需手动导入 SQL。
The database is created on first MySQL start; tables are created by the backend. No manual SQL import needed.

**持久化 / Persistence**（命名数据卷 named volumes，`docker compose down` 不会删除 / survive `down`）：

| 卷 Volume | 容器路径 Path | 内容 Content |
|---|---|---|
| `nan-mysql-data` | `/var/lib/mysql` | 全部业务数据 / all database data |
| `nan-upload-data` | `/data/upload` | 上传的小说与文件 / uploaded files |
| `nan-models-data` | `/data/models` | 基础模型、LoRA 适配器、训练任务 / models, adapters, jobs |
| `nan-novels-data` | `/data/novels` | 小说工作区与章节数据 / novel workspaces and chapters |

查看卷 / inspect volumes:

```powershell
docker volume ls
docker volume inspect nan-mysql-data
```

**备份 Backup**（在 `docker/` 目录执行；密码由容器内环境变量提供 / run in `docker/`; password comes from the container env）：

```powershell
# 密码在容器内读取，不出现在宿主机命令行 / password read inside the container
docker exec nan-mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --databases test10000' > backup-mysql.sql
```

上传文件与模型另行打包（体量较大）/ Also back up files & models:

```powershell
docker run --rm -v nan-upload-data:/data -v ${PWD}:/backup alpine tar czf /backup/upload-backup.tgz -C /data .
docker run --rm -v nan-models-data:/data -v ${PWD}:/backup alpine tar czf /backup/models-backup.tgz -C /data .
```

**恢复 Restore**：

```powershell
docker exec -i nan-mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < backup-mysql.sql

docker run --rm -v nan-upload-data:/data -v ${PWD}:/backup alpine sh -c "tar xzf /backup/upload-backup.tgz -C /data"
```

> 危险操作：`docker compose down -v` 会**同时删除数据卷**，仅在确认要清空环境时使用。
> WARNING: `docker compose down -v` DELETES the data volumes.

---

## 7. 交付到目标机器 / Delivery to Target Machines

### 7.1 目标机器可以联网 / Online target

1. 打包整个项目目录（或 `git clone`），确保包含 `backend/`、`frontend/`、`python-service/`、`docker/`。
2. 目标机安装 Docker Desktop / Docker Engine。
3. `cd docker` → `copy .env.example .env` → 修改密码和端口。
4. `docker compose up -d --build`。
5. 放行防火墙 TCP 端口（默认 Web **8080**；如需远程连库再放行 **3307**）。

### 7.2 目标机器不能联网（离线交付）/ Offline / air-gapped target

在一台**与目标机同 CPU 架构、能联网**的机器上准备镜像：

Prepare images on an online machine with the SAME CPU architecture:

```powershell
cd docker
# 1) 构建全部镜像 / build all images
docker compose build
docker pull mysql:8.0

# 2) 导出为离线包 / export image tarballs
docker save -o nan-images.tar nan-novel-backend:latest nan-novel-python:latest nan-novel-frontend:latest mysql:8.0

# 3) 连同项目源码目录一起拷贝到目标机（U盘/内网传输）
#    Copy nan-images.tar together with the project folder (esp. docker/)
```

在目标机 / On the target machine:

```powershell
docker load -i nan-images.tar
cd docker
copy .env.example .env
# 编辑 .env / edit .env
docker compose up -d          # 镜像已存在，无需联网拉取 / images present, no pull needed
docker compose ps
```

注意 / Notes:
- 镜像为按操作系统/CPU 架构构建的：在 Windows (x86_64) 上构建的镜像可用于 x86_64 Linux；若目标是 ARM（如部分国产服务器/树莓派），需在对应架构机器上构建，或用 `docker buildx --platform linux/arm64` 交叉构建。
- 离线环境下「远程大模型」需要目标机能访问对应的模型 API 地址；「HuggingFace 模型下载」在离线/内网环境不可用，可改为在「本地模型」页登记**已放入模型卷中的本地权重目录**。

---

## 8. 防火墙与访问地址 / Firewall & Access

- Linux 放行端口示例（ufw）：`sudo ufw allow 8080/tcp`（必要时再加 `3307/tcp`，不建议对公网开放数据库）。
- Windows：首次启动 Docker 发布端口时按提示允许专用网络；或在「高级安全 Windows Defender 防火墙」放行入站 TCP 8080。
- 访问地址：
  - 本机：<http://localhost:8080>
  - 局域网/服务器：`http://<服务器IP>:8080`
  - MySQL：`<服务器IP>:3307`（用户 root，密码取 `.env`；不建议对公网开放）。

Open inbound TCP 8080 (and 3307 only if you need remote DB access — not recommended on public networks).

---

## 9. 交付清单与设计说明 / Delivery Notes

**新增文件（全部在 `docker/`，另有 1 个根目录文件）/ New files:**

```
docker/
├── compose.yaml              # 主编排：mysql/backend/python/frontend
├── Dockerfile.backend        # Spring Boot 多阶段构建（JDK 17）
├── Dockerfile.python         # FastAPI 镜像（uv 安装依赖）
├── Dockerfile.frontend       # Node 构建 + nginx 托管
├── nginx/default.conf        # 静态托管 + /java /ai 反向代理
├── .env.example              # 环境变量模板（无真实密码）
└── README-Docker.md          # 本文档
.dockerignore                 # 根目录（见下方说明）
```

**为什么根目录有一个 `.dockerignore` / Why a root-level `.dockerignore`:**
Docker 只从「构建上下文根目录」读取 `.dockerignore`，不支持自定义路径。三个镜像的构建上下文都必须是仓库根目录（Dockerfile 需同时引用 `backend/`、`frontend/`、`python-service/`），因此该文件只能位于根目录。它排除了 `node_modules`、`target`、`upload/`、`models/`、`.venv`、密钥文件等，避免数 GB 无关文件进入构建上下文。

**对原有项目的修改 / Changes to existing files:** **无（零修改）**。没有改动任何业务代码、`application.yml`、前端源码或启动脚本；本地开发方式（`start.bat` / `npm run dev`）完全不变。容器内的连接信息全部通过环境变量注入：`SPRING_DATASOURCE_*`、`AI_SERVICE_URL`、`FILE_STORAGE_PATH`、`JAVA_BACKEND_URL`、`LOCAL_MODELS_DIR`。
No existing file was modified. Container wiring is 100% environment-variable driven.

**功能差异（容器模式下的已知限制）/ Known limitations in container mode:**
1. 「Python 环境检测」页是为宿主机开发流程设计的（Java 探测本机 python.exe），容器内无需使用，显示为空属正常；AI 服务本身已作为独立容器运行。
2. 容器内不安装 torch/CUDA，也不挂载宿主机显卡；本机推理与 QLoRA 微调请在宿主机 Python 环境进行（AI 服务本身仍可正常运行文本提取与远程大模型调用）。
3. 远程大模型 API Key 仍在网页端配置；HuggingFace 下载需要容器能访问外网（或使用已持久化的本地权重）。

---

## 10. 本次实际验证记录 / Verification performed

测试环境：Windows 11 + Docker Desktop（Engine 29.6.1，Linux 容器，WSL2）。

| 验证项 Check | 命令 Command | 结果 Result |
|---|---|---|
| Compose 语法与变量插值 | `docker compose config --quiet` | 通过 |
| 镜像构建 | `docker compose build` | 3 个镜像全部构建成功（MySQL 使用官方镜像） |
| 服务启动 | `docker compose up -d` | 4 个容器全部 `healthy` |
| 前端静态页 | `GET http://localhost:8080/` | 200 |
| Java 前端反代 | `GET /java/api/file/list` | `{"code":0,...,"data":[]}` |
| Python 前端反代 | `GET /ai/api/health` | `{"code":0,"message":"ok","data":null}` |
| 上传（经 nginx） | `POST /java/api/file/upload` | 成功，返回文件 id 与存储路径 |
| 预览（经 nginx） | `GET /java/api/file/preview/1` | 返回文件原文 |
| Python → Java 内网调用 | 容器内 `httpx.get("http://backend:8022/api/file/preview/1")` | 200 |
| 数据库自动建表 | `SHOW TABLES FROM test10000` | `file` / `novel_extract` / `ai_model_config` / `python_env` |
| 上传卷持久化 | 上传后 `docker exec nan-backend ls /data/upload/...` | 文件存在 |
| down → up 数据保持 | `docker compose down && up -d` | 文件记录与卷数据仍存在 |

> 说明：测试产生的示例文件与数据库记录已在验证后清理。
> Test artifacts were cleaned up after verification.

**环境排错备注 / Environment note:**
若 Docker Desktop 引擎持续返回 `500 ... /v1.55/info`，且日志出现
`vpnkit-bridge ... /run/guest-services/socketforwarder-receive-fds.sock: permission denied`，
请检查 `docker-desktop` 这个 WSL 发行版内的 `/etc/wsl.conf` 是否被设置了
`[user] default=<非root用户>`；Docker Desktop 要求该发行版以 root 运行，删除该文件后
`wsl --shutdown` 并重启 Docker Desktop 即可（本次验证环境即因此问题修复后通过）。
This is a Docker Desktop/WSL issue, unrelated to this project's compose files.
