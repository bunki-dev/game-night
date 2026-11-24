"""Shared data types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

GameKind = Literal["trivia", "hot_take"]
Audience = Literal["family", "adults"]


class Question(BaseModel):
    """One multiple-choice trivia question. Validated so a bad LLM output can't reach the screen."""

    prompt: str = Field(min_length=8, max_length=220)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field("", max_length=240)
    category: str = Field("general", max_length=40)
    difficulty: Literal["easy", "medium", "hard"] = "medium"

    @field_validator("options")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        cleaned = [o.strip() for o in v]
        if any(not o or len(o) > 80 for o in cleaned):
            raise ValueError("each option must be 1-80 characters")
        if len({o.lower() for o in cleaned}) != 4:
            raise ValueError("options must be distinct")
        return cleaned

    @model_validator(mode="after")
    def _answer_not_in_prompt(self) -> Question:
        answer = self.options[self.answer_index].lower()
        if len(answer) > 3 and answer in self.prompt.lower():
            raise ValueError("the question gives away its own answer")
        return self


class TriviaBatch(BaseModel):
    questions: list[Question]


class HotTakePrompt(BaseModel):
    text: str = Field(min_length=10, max_length=160)


class PromptBatch(BaseModel):
    prompts: list[HotTakePrompt]


class JudgedAnswer(BaseModel):
    player_id: str
    score: int = Field(ge=0, le=10)
    comment: str = Field(max_length=140)


class Judgement(BaseModel):
    results: list[JudgedAnswer]
