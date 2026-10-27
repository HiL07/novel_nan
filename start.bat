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
rem 1 = 同时启动 llama.cpp（start-llama.bat，本地 GGUF 模型 :8001）；0 = 不启动（默认）
rem 平时在网页「llama.cpp」页选模型启动即可（AI 服务关闭时自动关闭）；两种方式都用 8001，同时只能开一个
set "START_LLAMA=0"

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
echo [1/4] 启动后端  mvn spring-boot:run   -^>  http://localhost:8022
start "文件管理-后端" /D "%BACKEND_DIR%" cmd /k "mvn spring-boot:run"

rem 等后端先起，避免同时抢占资源
ping -n 4 127.0.0.1 >nul

rem ==================== 启动 AI 服务 ====================
rem 小说提取调用「模型配置」中启用的模型（默认 DeepSeek，Key 在 backendpplication-secret.yml）
rem Python 解释器：优先用「Python 环境」页检测通过并保存的路径（python-service\.python-env），否则用项目 venv
set "PYEXE="
if exist "%ROOT%python-service\.python-env" set /p PYEXE=<"%ROOT%python-service\.python-env"
if defined PYEXE if not exist "%PYEXE%" (
    echo [提示] 已保存的 Python 不存在：%PYEXE%，改用项目 venv
    set "PYEXE="
)
if not defined PYEXE if exist "%ROOT%python-service\.venv\Scripts\python.exe" set "PYEXE=%ROOT%python-service\.venv\Scripts\python.exe"
if defined PYEXE (
    echo [2/4] 启动 AI 服务  %PYEXE%  -^>  http://localhost:8021
    start "文件管理-AI服务" /D "%ROOT%python-service" cmd /k ""%PYEXE%" -m uvicorn app.main:app --port 8021"
) else (
    echo [2/4] 跳过 AI 服务：未配置 Python。请启动后在「Python 环境」页面选择并检测
)

rem ==================== 启动 llama.cpp ====================
rem 本地 GGUF 模型服务，独立窗口（关窗口即停）；模型和参数见 start-llama.bat，已在运行则自动跳过
if "%START_LLAMA%"=="1" if exist "%ROOT%start-llama.bat" (
    echo [3/4] 启动 llama.cpp  start-llama.bat  -^>  http://127.0.0.1:8001/v1
    start "文件管理-llama" /D "%ROOT%" cmd /c ""%ROOT%start-llama.bat""
    goto :llama_done
)
echo [3/4] 跳过 llama.cpp（START_LLAMA=%START_LLAMA%）
:llama_done

rem ==================== 启动前端 ====================
echo [4/4] 启动前端  npm run dev           -^>  http://localhost:5173
start "文件管理-前端" /D "%FRONTEND_DIR%" cmd /k "npm run dev"

echo.
echo ==========================================
echo  已在新窗口启动，关闭对应窗口即停止服务。
echo  后端：http://localhost:8022
echo  AI 服务：http://localhost:8021
echo  前端：http://localhost:5173
if "%START_LLAMA%"=="1" echo  llama：http://127.0.0.1:8001/v1（模型配置里填这个，并发 1）
echo ==========================================
echo.
pause
