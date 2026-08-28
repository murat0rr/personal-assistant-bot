from abc import ABC, abstractmethod

from groq import AsyncGroq

from src.core.config import settings

_WHISPER_MODEL = "whisper-large-v3-turbo"


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, filename: str) -> str: ...


class GroqSTT(SpeechToText):
    def __init__(self, api_key: str) -> None:
        self._client = AsyncGroq(api_key=api_key)

    async def transcribe(self, audio_bytes: bytes, filename: str) -> str:
        response = await self._client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model=_WHISPER_MODEL,
            language="ru",
        )
        return response.text


stt: SpeechToText = GroqSTT(settings.groq_api_key)
