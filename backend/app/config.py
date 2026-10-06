"""集中式配置：所有环境变量和密钥只在这里出现一次。"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- 模型 ---
    model_provider: str = "doubao"            # doubao | deepseek | qwen | gpt
    doubao_model: str = ""
    doubao_api_key: str = ""
    doubao_base_url: str = ""


    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    gpt_api_key: str = ""
    temperature: float = 0.2                    # 编程任务要低温度，稳

    # --- Embedding（M6 用） ---
    doubao_embedding_model: str = ""
    doubao_embedding_api_key: str = ""
    doubao_embedding_base_url: str = ""

    # --- infra 基础设施 ---
    database_url: str = "postgresql+psycopg://codelin:codelin@localhost:5432/codelin"
    checkpoint_db_url: str = "postgresql://codelin:codelin@localhost:5432/codelin"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 60 * 24 * 7

    # --- 可观测（M9 用） ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()