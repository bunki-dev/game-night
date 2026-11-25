"""Shared data types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

GameKind = Literal["trivia", "hot_take", "fake_out", "most_likely", "emoji"]
GAMES: tuple[str, ...] = ("trivia", "hot_take", "fake_out", "most_likely", "emoji")
MIN_PLAYERS = {"trivia": 1, "hot_take": 2, "fake_out": 2, "most_likely": 3, "emoji": 1}
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


class Fact(BaseModel):
    """Fake Out: a true but surprising fact with one blank. Players invent fake answers to fool each other."""

    prompt: str = Field(min_length=12, max_length=200)
    answer: str = Field(min_length=1, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("prompt")
    @classmethod
    def _one_blank(cls, v: str) -> str:
        if v.count("___") != 1:
            raise ValueError("the fact needs exactly one ___ blank")
        return v.strip()

    @model_validator(mode="after")
    def _answer_not_in_prompt(self) -> Fact:
        if len(self.answer) > 3 and self.answer.lower() in self.prompt.lower():
            raise ValueError("the fact gives away its own answer")
        return self


class EmojiPuzzle(BaseModel):
    """Emoji Decode: a film, song or saying written in emoji."""

    emojis: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=2, max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=6)
    category: Literal["film", "song", "saying", "tv show", "place", "book"] = "film"

    @field_validator("emojis")
    @classmethod
    def _no_letters(cls, v: str) -> str:
        if any(ch.isascii() and ch.isalnum() for ch in v):
            raise ValueError("emoji only: no letters or numbers")
        return v.strip()
