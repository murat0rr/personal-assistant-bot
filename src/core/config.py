from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_user_id: int
    bot_access_password: str = "это читинец"

    claude_api_key: str = ""
    claude_base_url: str | None = None
    claude_model_haiku: str = "claude-haiku-4-5"
    claude_model_sonnet: str = "claude-sonnet-5"
    groq_api_key: str = ""
    notion_api_key: str = ""
    notion_webhook_secret: str = ""
    notion_diary_db_id: str = ""
    notion_notes_db_id: str = ""
    tasker_webhook_secret: str = ""
    weather_city: str = ""
    database_url: str = ""
    redis_url: str = ""
    timezone: str = "Europe/Moscow"
    # Лёгкий staging для Mini App (SPEC.md §5) — полный URL /miniapp-staging/
    # на проде; пусто = команда /staging отвечает, что не настроено.
    staging_miniapp_url: str = ""
    # Полный URL боевого /miniapp/ — используется для кнопки меню чата
    # (см. telegram_bot.py::main, set_chat_menu_button), чтобы открывать
    # Mini App прямо из строки чата в списке чатов, в один тап, без
    # /start и лишних кнопок. Пусто = кнопку меню не трогаем.
    miniapp_url: str = ""


settings = Settings()
