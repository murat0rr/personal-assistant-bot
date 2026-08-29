import logging

from aiogram import F, Router
from aiogram.types import Message

from src.core.auth import is_authorized
from src.integrations.claude_client import summarize_finance_csv

logger = logging.getLogger(__name__)

router = Router()

FINANCE_GUIDE = (
    "💳 Пора собрать расходы за прошлый месяц.\n\n"
    "Как выгрузить выписку из Т-Банка (пункты меню могут немного отличаться "
    "в зависимости от версии приложения):\n"
    "1. Открой счёт/карту, с которой хочешь выписку.\n"
    "2. «Выписки и справки» → «Выписка по счёту».\n"
    "3. Период — «прошлый месяц», формат — CSV.\n"
    "4. Скачай файл и перешли его сюда, как документ."
)

_CSV_EXTENSIONS = (".csv",)
_CSV_MIME_TYPES = ("text/csv", "application/vnd.ms-excel", "application/csv")


def _looks_like_csv(filename: str | None, mime_type: str | None) -> bool:
    if filename and filename.lower().endswith(_CSV_EXTENSIONS):
        return True
    return mime_type in _CSV_MIME_TYPES


def _decode_csv(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251")


@router.message(F.document)
async def handle_finance_csv(message: Message) -> None:
    if not message.from_user or not is_authorized(message.from_user.id):
        await message.answer("Извините, этот бот вам недоступен.")
        return

    document = message.document
    if document is None or not _looks_like_csv(document.file_name, document.mime_type):
        await message.answer("Похоже, это не CSV-выписка — распознаю только .csv файлы.")
        return

    try:
        file = await message.bot.download(document.file_id)
        raw = file.read()
        csv_text = _decode_csv(raw)[:15000]
        summary = await summarize_finance_csv(csv_text)
    except Exception:
        logger.exception("Не удалось разобрать CSV-выписку: %r", document.file_name)
        await message.answer("Не получилось разобрать файл, попробуй ещё раз.")
        return

    await message.answer(summary)
