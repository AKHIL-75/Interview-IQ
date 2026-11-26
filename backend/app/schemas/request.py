"""Bounded external request values; model-output schemas remain independent."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[str, StringConstraints(
    min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
QuestionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=10000)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
