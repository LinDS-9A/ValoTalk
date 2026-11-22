"""修 .gitignore：把 config.json 的所有备份变体也排除。

背景：config.json.bak-switch / config.json.before-restore 里都含真实 API key，
虽然 git 目前没跟踪它们，但一旦 git add -A 就会进仓库。
顺便把乱码注释换成正常 UTF-8。
"""
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = ROOT / ".gitignore"

content = """# ---- 本地配置：含 API key，绝不入库 ----
config.json
config.json.*
config.local.json

# ---- 模型权重 / 缓存 / 日志 ----
models/
cache/
logs/
*.npy
*.onnx
*.mp3
*.wav

# ---- Python ----
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/

# ---- 编辑器 / 系统 ----
.vscode/
.idea/
.DS_Store
Thumbs.db
desktop.ini

# ---- 诊断截图（含游戏画面/聊天） ----
*.png
*.jpg
!docs/*.png

# ---- 发布用临时文件 ----
.release_notes.md
dist/
"""

io.open(p, "w", encoding="utf-8", newline="\n").write(content)
print("已重写 .gitignore")

# 验证关键项
import subprocess
git = r"E:\rea-work\.tools\git\cmd\git.exe"
for f in ("config.json", "config.json.bak-switch",
          "config.json.before-restore", ".release_notes.md"):
    r = subprocess.run([git, "check-ignore", "-q", f],
                       cwd=str(ROOT), capture_output=True)
    print(f"  {f:32s} {'已忽略 ✓' if r.returncode == 0 else '未忽略 ✗'}")