"""Only plain question text and the five explicitly supported voices are accepted."""
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

AzureVoice = Literal[
    "en-IN-NeerjaNeural", "en-IN-PrabhatNeural", "en-IN-AaravNeural",
    "en-US-JennyNeural", "en-US-BrianNeural",
]
ALLOWED_AZURE_VOICES = frozenset(get_args(AzureVoice))
DEFAULT_AZURE_VOICE = "en-US-JennyNeural"


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=3000, strict=True)
    voice: AzureVoice = DEFAULT_AZURE_VOICE
