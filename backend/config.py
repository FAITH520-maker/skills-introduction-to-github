"""应用配置：从环境变量 / .env 读取 LLM 配置与路径。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent  # backend/
PROJECT_DIR = BASE_DIR.parent  # 项目根目录
FRONTEND_DIR = PROJECT_DIR / "frontend"
DATA_DIR = PROJECT_DIR / "data"
SESSION_DIR = DATA_DIR / "sessions"


def _load_dotenv() -> None:
    """极简 .env 加载器（不引入额外依赖）。"""
    env_file = PROJECT_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.api_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
        self.base_url = (
            os.environ.get("LLM_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com"
        ).rstrip("/")
        self.model = os.environ.get("LLM_MODEL") or "deepseek-chat"
        self.timeout = float(os.environ.get("LLM_TIMEOUT", "120"))
        self.mock = os.environ.get("LLM_MOCK", "").strip().lower() in {"1", "true", "yes"}

        SESSION_DIR.mkdir(parents=True, exist_ok=True)
