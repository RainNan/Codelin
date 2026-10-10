"""集中式配置：所有环境变量和密钥只在这里出现一次。"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Stable absolute roots, independent of the server's current directory.
    workspace_root: str = str(Path(__file__).resolve().parents[1] / "workspaces")
    file_lock_root: str = str(Path(__file__).resolve().parents[1] / ".file-locks")
    max_file_bytes: int = 2 * 1024 * 1024
    file_lock_timeout: float = 10.0

    # --- 模型 ---
    model_provider: str = "doubao"  # doubao | deepseek | qwen | gpt
    doubao_model: str = ""
    doubao_api_key: str = ""
    doubao_base_url: str = ""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    gpt_api_key: str = ""
    temperature: float = 0.2
    title_timeout_seconds: float = 15.0

    # --- Embedding ---
    doubao_embedding_model: str = ""
    doubao_embedding_api_key: str = ""
    doubao_embedding_base_url: str = ""

    # --- infra 基础设施 ---
    database_url: str = "postgresql+psycopg://codelin:codelin123@localhost:5432/codelin"
    checkpoint_db_url: str = "postgresql://codelin:codelin123@localhost:5432/codelin"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "9KdP2sR7xQzL5nT8bV3cM1jF4gH6aW0eY"  # JWT服务器密钥
    jwt_expire_minutes: int = 60 * 24 * 7

    # --- langfuse ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
