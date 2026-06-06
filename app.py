"""Weekend Agent — 一键启动: python app.py"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent


def _resolve_frontend_dir() -> Path | None:
    for name in ("frontend", "frontend-v2"):
        path = PROJECT_ROOT / name
        if path.is_dir() and (path / "package.json").is_file():
            return path
    return None


def build_frontend() -> bool:
    """构建前端产物；失败时返回 False 但不阻止后端启动。"""
    frontend_dir = _resolve_frontend_dir()
    if frontend_dir is None:
        print("  [warn] 未找到 frontend/ 或 frontend-v2/，跳过前端构建")
        return False

    frontend_dist = frontend_dir / "dist"

    src_marker = frontend_dir / "src" / "App.tsx"
    dist_marker = frontend_dist / "index.html"
    if (
        frontend_dist.is_dir()
        and dist_marker.is_file()
        and src_marker.is_file()
        and dist_marker.stat().st_mtime >= src_marker.stat().st_mtime
    ):
        print(f"  [ok] 前端产物已是最新 ({frontend_dir.name}/dist)，跳过构建")
        return True

    print(f"  [build] 正在构建 {frontend_dir.name}/ ...")
    try:
        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        print("  [ok] 前端构建完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [warn] 前端构建失败:\n{e.stderr}")
        return False
    except FileNotFoundError:
        print("  [warn] 未找到 npm，跳过前端构建。请手动执行: cd frontend && npm run build")
        return False


if __name__ == "__main__":
    print("\n  Weekend Agent 启动中...\n")
    build_frontend()

    print("\n  打开浏览器: http://127.0.0.1:8000/\n")

    # Windows 下 reload=True 易残留双进程，导致 8000 端口卡死、页面白屏
    use_reload = sys.platform != "win32"

    uvicorn.run(
        "backend.server:app",
        host="127.0.0.1",
        port=8000,
        reload=use_reload,
    )
