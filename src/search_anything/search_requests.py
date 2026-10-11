"""Validated options shared by search producers and workers."""

import math
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from search_anything.retrieval import DEFAULT_WEIGHTS


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8192)
    mode: str = Field(default="hybrid", pattern="^(hybrid|semantic|keyword)$")
    representation_mode: str = Field(
        default="separate", pattern="^(separate|combined|both)$"
    )
    limit: int = Field(default=10, ge=1, le=50)
    candidate_limit: int = Field(default=60, ge=10, le=200)
    content_types: list[str] | None = Field(default=None, max_length=32)
    asset_ids: list[UUID] | None = Field(default=None, max_length=100)
    weights: dict[str, float] | None = None
    similarity_cutoffs: dict[str, float] | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, query: str) -> str:
        clean = query.strip()
        if not clean:
            raise ValueError("search query cannot be empty")
        return clean

    @field_validator("weights")
    @classmethod
    def validate_weights(
        cls, weights: dict[str, float] | None
    ) -> dict[str, float] | None:
        if weights is None:
            return None
        if set(weights) - set(DEFAULT_WEIGHTS):
            raise ValueError("unknown search channel weight")
        if any(
            not math.isfinite(value) or not 0 <= value <= 10
            for value in weights.values()
        ):
            raise ValueError(
                "search channel weights must be finite and between 0 and 10"
            )
        return weights

    @field_validator("similarity_cutoffs")
    @classmethod
    def validate_similarity_cutoffs(
        cls, cutoffs: dict[str, float] | None
    ) -> dict[str, float] | None:
        if cutoffs is None:
            return None
        dense_channels = {
            "text",
            "transcript",
            "ocr",
            "image",
            "audio",
            "video",
            "combined",
        }
        if set(cutoffs) - dense_channels:
            raise ValueError(
                "similarity cutoffs must use dense representation channels"
            )
        if any(
            not math.isfinite(value) or not -1 <= value <= 1
            for value in cutoffs.values()
        ):
            raise ValueError(
                "cosine similarity cutoffs must be finite and between -1 and 1"
            )
        return cutoffs

    @model_validator(mode="after")
    def validate_limits_and_enabled_weights(self) -> "SearchRequest":
        if self.candidate_limit < self.limit:
            raise ValueError("candidate_limit must be at least limit")
        resolved_weights = {**DEFAULT_WEIGHTS, **(self.weights or {})}
        if not any(resolved_weights.values()):
            raise ValueError("at least one search channel weight must be positive")
        return self
