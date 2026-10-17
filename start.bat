@echo off
chcp 936 >nul
setlocal

title 文件管理 - 一键启动

rem ==================== 基本信息 ====================
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"

rem ============ 本机环境路径（换机器时改这里） ============
rem 后端需要 JDK 17；本机默认 JAVA_HOME 指向 JDK 8，必须在这里覆盖
set "JAVA17_HOME=D:\workplace\jdk17\jdk-17.0.12_windows-x64_bin\jdk-17.0.12"
set "MAVEN_BIN=D:\workplace\maven\maven-3.8.6\bin"
set "NODE_DIR=D:\workplace\node.js"

echo ==========================================
echo            文件管理 - 一键启动
echo ==========================================
echo.

rem ==================== 环境检查 ====================
if not exist "%JAVA17_HOME%\bin\java.exe" (
    echo [错误] 未找到 JDK 17：%JAVA17_HOME%
    echo        请修改脚本顶部的 JAVA17_HOME。
    echo.
    pause
    exit /b 1
)
if not exist "%MAVEN_BIN%\mvn.cmd" (
    echo [错误] 未找到 Maven：%MAVEN_BIN%\mvn.cmd
    echo        请修改脚本顶部的 MAVEN_BIN。
    echo.
    pause
    exit /b 1
)
if not exist "%BACKEND_DIR%\pom.xml" (
    echo [错误] 未找到后端工程：%BACKEND_DIR%\pom.xml
    echo.
    pause
    exit /b 1
)
if not exist "%FRONTEND_DIR%\package.json" (
    echo [错误] 未找到前端工程：%FRONTEND_DIR%\package.json
    echo.
    pause
    exit /b 1
)

set "JAVA_HOME=%JAVA17_HOME%"
set "PATH=%JAVA17_HOME%\bin;%MAVEN_BIN%;%NODE_DIR%;%PATH%"

rem ==================== 启动后端 ====================
echo [1/3] 启动后端  mvn spring-boot:run   -^>  http://localhost:8022
start "文件管理-后端" /D "%BACKEND_DIR%" cmd /k "mvn spring-boot:run"

rem 等后端先起，避免同时抢占资源
ping -n 4 127.0.0.1 >nul

rem ==================== 启动 AI 服务 ====================
rem 小说提取调用「模型配置」中启用的模型（默认 DeepSeek，Key 在 backendpplication-secret.yml）
if exist "%ROOT%python-service\.venv\Scripts\python.exe" (
    echo [2/3] 启动 AI 服务  uvicorn app.main:app  -^>  http://localhost:8021
    start "文件管理-AI服务" /D "%ROOT%python-service" cmd /k ".venv\Scripts\python -m uvicorn app.main:app --port 8021"
) else (
    echo [2/3] 跳过 AI 服务：未找到 python-service\.venv，请先按 CLAUDE.md 创建虚拟环境
)

rem ==================== 启动前端 ====================
echo [3/3] 启动前端  npm run dev           -^>  http://localhost:5173
start "文件管理-前端" /D "%FRONTEND_DIR%" cmd /k "npm run dev"

echo.
echo ==========================================
echo  已在新窗口启动，关闭对应窗口即停止服务。
echo  后端：http://localhost:8022
echo  AI 服务：http://localhost:8021
echo  前端：http://localhost:5173
echo ==========================================
echo.
pause
