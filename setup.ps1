# ValoTalk 一键安装
# 用法：右键 → 使用 PowerShell 运行，或在终端里
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -CheckOnly   # 只看会选哪个 Python，不装

param([switch]$CheckOnly)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "`n=== ValoTalk 安装 ===`n" -ForegroundColor Cyan

# ---------- 1. 找 Python ----------
# ⚠️ 只认 3.10 ~ 3.14。3.15 能装 ctranslate2（有 cp315 轮子），但 onnxruntime
#    目前只出到 cp314 —— 装到最后一步会整个失败，报的还是看不懂的
#    "No matching distribution found for onnxruntime"。与其让人踩，不如这里就挑对。
$MAX_MINOR = 14
$candidates = @("python", "py", "D:\python\python.exe", "C:\Python314\python.exe",
                "C:\Python313\python.exe", "C:\Python312\python.exe", "C:\Python311\python.exe",
                "C:\Python310\python.exe")
$PY = $null
$seen = @()
foreach ($c in $candidates) {
    try {
        $v = & $c -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $v) { continue }
        $seen += "$c -> $v"
        $parts = $v.Trim().Split(".")
        $maj = [int]$parts[0]; $min = [int]$parts[1]
        if ($maj -eq 3 -and $min -ge 10 -and $min -le $MAX_MINOR) {
            $PY = $c
            Write-Host "找到 Python $v  ->  $c" -ForegroundColor Green
            break
        }
        Write-Host "跳过 Python $v（$c）：需要 3.10 ~ 3.$MAX_MINOR" -ForegroundColor DarkGray
    } catch { }
}
if (-not $PY) {
    Write-Host "`n没找到可用的 Python（需要 3.10 ~ 3.$MAX_MINOR）。" -ForegroundColor Red
    if ($seen.Count) {
        Write-Host "本机装的是：" -ForegroundColor DarkYellow
        $seen | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
        Write-Host "`n3.15 目前缺 onnxruntime 的轮子，装了会失败。" -ForegroundColor DarkYellow
    }
    Write-Host "去 https://www.python.org/downloads/ 装个 3.13，记得勾 Add Python to PATH。"
    Read-Host "按回车退出"
    exit 1
}

# ---------- 2. 建独立环境 ----------
# run.bat 优先用 .venv，装这里不污染系统 Python，也不会和别的项目抢依赖版本。
$VENV = Join-Path $here ".venv"
$VPY = Join-Path $VENV "Scripts\python.exe"
if (-not (Test-Path $VPY)) {
    Write-Host "`n[0/4] 建虚拟环境 .venv …" -ForegroundColor Yellow
    & $PY -m venv $VENV
    if (-not (Test-Path $VPY)) {
        Write-Host "建 venv 失败（$VENV）" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
    Write-Host "  venv: $VPY"
} else {
    Write-Host "`n[0/4] 已有 .venv，复用：$VPY" -ForegroundColor DarkGray
}
$PY = $VPY

if ($CheckOnly) {
    Write-Host "`n(-CheckOnly) 到此为止：会用 $PY" -ForegroundColor Cyan
    exit 0
}

# ---------- 3. 装依赖 ----------
$env:PIP_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple"
$env:PIP_TRUSTED_HOST = "mirrors.aliyun.com"
$env:HF_ENDPOINT = "https://hf-mirror.com"

Write-Host "`n[1/4] 安装 Python 依赖（阿里云镜像，约 1.5GB）…" -ForegroundColor Yellow
& $PY -m pip install --upgrade pip
& $PY -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n依赖安装失败。常见原因：" -ForegroundColor Red
    Write-Host "  · Python 版本不对（需要 3.10 ~ 3.$MAX_MINOR，3.15 缺 onnxruntime 轮子）" -ForegroundColor DarkYellow
    Write-Host "  · 网络问题：删掉 .venv 重跑本脚本" -ForegroundColor DarkYellow
    Write-Host "  · 想在 3.13 上用旧 OCR 包 rapidocr-onnxruntime —— 它 pin 了 <3.13，装不上，" -ForegroundColor DarkYellow
    Write-Host "    requirements.txt 里已经按版本分流成新版 rapidocr，代码两种都认" -ForegroundColor DarkYellow
    Read-Host "按回车退出"
    exit 1
}

Write-Host "`n[2/4] 安装 GPU 加速库（NVIDIA 显卡，约 1.2GB；没有就跳过）…" -ForegroundColor Yellow
Write-Host "      没有这一步，识别会慢 15 倍以上，基本没法实时用。" -ForegroundColor DarkGray
& $PY -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
if ($LASTEXITCODE -ne 0) {
    Write-Host "  GPU 库没装上，会走 CPU（很慢）。可以稍后单独装。" -ForegroundColor DarkYellow
}

# ---------- 4. 预下模型 + 自检 ----------
Write-Host "`n[3/4] 预下载语音识别模型 small（约 480MB，走 hf-mirror）…" -ForegroundColor Yellow
Write-Host "      想更小可以改用 base/tiny：改 config.json 里 asr.model" -ForegroundColor DarkGray
& $PY -X utf8 -c @"
import os
os.environ.setdefault('HF_ENDPOINT','https://hf-mirror.com')
from faster_whisper import WhisperModel
import numpy as np
m = WhisperModel('small', device='cpu', compute_type='int8', download_root='models', num_workers=1)
m.transcribe(np.zeros(16000, dtype=np.float32), language='en')[0]
print('模型就绪')
"@

Write-Host "`n[4/4] 环境自检" -ForegroundColor Yellow
& $PY -X utf8 tools\probe_env.py

Write-Host "`n=== 装完了。双击 run.bat 启动。 ===" -ForegroundColor Cyan
Write-Host "别忘了按 README 第 2 节改游戏里的麦克风设置。" -ForegroundColor Cyan
Read-Host "按回车关闭"