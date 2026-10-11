from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class Feedback(Base):
    """Обратная связь от пользователей бота (Phase 85, предложение:
    https://claude.ai/artifact/8xwZx1gqfuuM2KRKmSrNfA) — баги/идеи/
    пожелания, не только от владельца (в отличие от дневника/заметок),
    весь смысл фичи в том, чтобы собирать мнение остальных авторизованных
    пользователей тоже.

    Сам бот (handlers/f_feedback.py) заполняет только user_id/text —
    никакого похода в ИИ и никакого доступа к коду синхронно в хендлере.
    category/ai_summary/ai_rationale/auto_applicable заполняет фоновый
    ИИ-триаж сразу после вставки (core/feedback.py::triage_feedback_task)
    — это классификатор, его результат никогда не исполняется напрямую.
    status/resolution_note/commit_sha дальше двигает только периодический
    облачный агент через adapters/internal_api.py (отдельный секрет,
    не Telegram initData) — бот и API-процесс сами код не меняют и не
    коммитят."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- заполняет фоновый ИИ-триаж, бот сюда не пишет ---
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_applicable: Mapped[bool] = mapped_column(default=False, server_default="false")

    # --- заполняет периодический агент (adapters/internal_api.py) ---
    # new -> triaged -> (queued ->) done / needs_discussion / rejected / spam
    status: Mapped[str] = mapped_column(String, nullable=False, default="new", server_default="new")
    resolution_note: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
