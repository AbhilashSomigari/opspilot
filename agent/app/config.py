from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_api_key: str = "EMPTY"
    vllm_model: str = "Salesforce/xLAM-2-3b-fc-r"
    embedding_model: str = "text-embedding-3-small"
    database_url: str = "postgresql://opspilot:opspilot@postgres:5432/opspilot"
    prometheus_url: str = "http://prometheus:9090"
    jaeger_url: str = "http://jaeger:16686"
    log_dir: str = "/var/log/opspilot"
    github_token: str | None = None
    github_repository: str | None = None
    repo_root: str = "/workspace"
    model_input_cost_per_1m: float = 0.0
    model_output_cost_per_1m: float = 0.0

settings = Settings()
