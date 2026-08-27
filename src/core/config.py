from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_user_id: int

    claude_api_key: str = ""
    groq_api_key: str = ""
    notion_api_key: str = ""
    notion_webhook_secret: str = ""
    tasker_webhook_secret: str = ""
    database_url: str = ""
    redis_url: str = ""


settings = Settings()
