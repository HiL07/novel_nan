@echo off
chcp 936 >nul
setlocal

rem ============================================================
rem  启动本地 llama.cpp 服务（OpenAI 兼容接口，给「模型配置」用）
rem  用法：双击 = 用下面的默认模型；把 .gguf 拖到本文件上 = 用那个模型
rem        命令行：start-llama.bat [gguf 路径] [上下文长度]
rem  服务在本窗口里运行，关闭本窗口即停止服务。
rem  「模型配置」里填：http://127.0.0.1:8001/v1 ，并发 1
rem ============================================================

rem ============ 本机路径（换机器时改这里） ============
set "LLAMA_DIR=D:\workplace\llama.cpp_cuda12-12.4\llama-b9538-bin-win-cuda-12.4-x64"
set "DEFAULT_MODEL=E:\workplace\model\qwen3-4B-Instruct-2507\Qwen3-4B-inseruct-2507-GGUF\Qwen3-4B-Instruct-2507-Q4_K_M-GGUF\Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
set "FALLBACK_MODEL=%LLAMA_DIR%\model\qwen2.5-7b-instruct-q5_k_m-merged.gguf"
set "PORT=8001"
rem 上下文长度：12288 够小说提取（每块 6000 字 + 提示词 + 输出）；显存够可调 16384。
rem 写作工作区里的上下文窗口不要超过这里
set "CTX=12288"
rem GPU 层数：99 = 全部放进显存；显存不够时调小（其余层在 CPU 上跑，会变慢）
set "NGL=99"

set "MODEL=%DEFAULT_MODEL%"
if not "%~1"=="" set "MODEL=%~f1"
if not "%~2"=="" set "CTX=%~2"

if not exist "%LLAMA_DIR%\llama-server.exe" (
    echo [错误] 找不到 llama-server.exe：%LLAMA_DIR%
    echo        请修改本文件开头的 LLAMA_DIR。
    pause
    exit /b 1
)

if not exist "%MODEL%" (
    if "%~1"=="" if exist "%FALLBACK_MODEL%" (
        echo [提示] 默认模型不存在：%MODEL%
        echo        先改用：%FALLBACK_MODEL%
        echo.
        set "MODEL=%FALLBACK_MODEL%"
        goto :check_port
    )
    echo [错误] 模型文件不存在：%MODEL%
    pause
    exit /b 1
)

:check_port
netstat -ano | findstr /r /c:"127.0.0.1:%PORT% .*LISTENING" /c:"0.0.0.0:%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo [提示] 端口 %PORT% 已被占用，llama 服务可能已经在运行。
    echo        检查：http://127.0.0.1:%PORT%/health
    echo        本窗口 5 秒后自动关闭。
    ping -n 6 127.0.0.1 >nul
    exit /b 0
)

for %%F in ("%MODEL%") do set "MODEL_NAME=%%~nxF"
title llama-server :%PORT% %MODEL_NAME%

echo ==========================================
echo   llama.cpp 服务
echo   模型：%MODEL%
echo   地址：http://127.0.0.1:%PORT%/v1
echo   上下文：%CTX%   GPU 层数：%NGL%
echo   关闭本窗口即停止服务
echo ==========================================
echo.

rem --parallel 1 --cache-ram 0：RTX 4060 Laptop 上的稳定配置
rem （默认 4 个并发槽 + 8GB prompt cache 运行约 15 分钟后会 CUDA error 崩溃）
"%LLAMA_DIR%\llama-server.exe" -m "%MODEL%" --host 127.0.0.1 --port %PORT% -c %CTX% -ngl %NGL% --parallel 1 --cache-ram 0

echo.
echo [llama-server 已退出，退出码 %errorlevel%]
pause
