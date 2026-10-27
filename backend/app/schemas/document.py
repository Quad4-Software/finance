from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

DocumentFormat = Literal["pdf", "html"]
DocumentPeriod = Literal["last_month", "last_quarter", "ytd", "custom"]


class DocumentGenerateRequest(BaseModel):
    """Shared options for both downloadable document types.

    ``sections`` is an allowlist: omitted means every section, a non-empty
    list keeps only those keys. Unknown keys are rejected per document type
    by the route, which owns the allowed set.
    """

    format: DocumentFormat = "pdf"
    period: DocumentPeriod = "last_quarter"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    sections: Optional[list[str]] = None
    title: Optional[str] = Field(default=None, max_length=120)
    subtitle: Optional[str] = Field(default=None, max_length=200)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.upper() if value else value

    @field_validator("sections")
    @classmethod
    def _dedupe_sections(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return value
        seen: set[str] = set()
        deduped: list[str] = []
        for key in value:
            if key not in seen:
                seen.add(key)
                deduped.append(key)
        return deduped
