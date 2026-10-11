from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.models.task import Base


class BuildRequest(Base):
    """`/build` — мгновенная реализация по запросу владельца (Phase 85,
    предложение: https://claude.ai/artifact/8xwZx1gqfuuM2KRKmSrNfA, §8).
    В отличие от Feedback — только владелец (handlers/f_build.py гейтит
    по settings.telegram_user_id, не is_authorized), и текст запроса тут
    не данные для классификации, а легитимная инструкция: approve
    владельца — единственный предохранитель, узкого allowlist, как у
    автофикса чужих багов, здесь нет.

    Один активный запрос за раз (см. f_build.py — новый /build, пока
    текущий не в терминальном статусе, отклоняется). plan_text/
    chat_id/plan_message_id заполняет периодический облачный агент
    (adapters/internal_api.py, тот же секрет, что у Feedback) на
    шаге планирования; status дальше двигают и агент, и колбэки кнопок
    в самом боте (approve/reject/clarify)."""

    __tablename__ = "build_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authorized_users.telegram_user_id"), nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # pending_plan -> awaiting_approval -> approved -> in_progress
    #             -> done / needs_input / failed
    #             (awaiting_approval -> rejected, тупиковый)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending_plan", server_default="pending_plan"
    )
    plan_text: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
