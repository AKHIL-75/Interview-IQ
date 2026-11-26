"""Optional technical scope; absent means the existing general interview."""
from typing import Literal
from pydantic import model_validator
from app.schemas.request import RequestModel

CoreSubject = Literal["Java", "OOP", "DSA", "DBMS and SQL", "Operating Systems", "Computer Networks"]


class SubjectRequest(RequestModel):
    subject: CoreSubject | None = None

    @model_validator(mode="after")
    def technical_subject_only(self):
        if self.subject and getattr(self, "interview_type", "Technical") != "Technical":
            raise ValueError("Subject selection requires a Technical interview.")
        return self
