from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_user_id: int

    claude_api_key: str = ""
    claude_base_url: str | None = None
    claude_model_haiku: str = "claude-haiku-4-5"
    claude_model_sonnet: str = "claude-sonnet-5"
    groq_api_key: str = ""
    notion_api_key: str = ""
    notion_webhook_secret: str = ""
    notion_tasks_db_id: str = ""
    notion_diary_db_id: str = ""
    notion_habits_db_id: str = ""
    notion_notes_db_id: str = ""
    tasker_webhook_secret: str = ""
    database_url: str = ""
    redis_url: str = ""
    timezone: str = "Europe/Moscow"


settings = Settings()
