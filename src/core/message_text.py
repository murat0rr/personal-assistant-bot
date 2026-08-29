from aiogram.types import Message

from src.integrations.stt import stt


async def extract_text(message: Message) -> str | None:
    """Достать текст из сообщения: голос -> STT, иначе текст как есть.
    Общий хелпер для orchestrator.py и mode_buttons.py."""
    if message.voice:
        assert message.bot is not None
        file = await message.bot.get_file(message.voice.file_id)
        assert file.file_path is not None
        buf = await message.bot.download_file(file.file_path)
        assert buf is not None
        return await stt.transcribe(buf.read(), "voice.ogg")
    return message.text
