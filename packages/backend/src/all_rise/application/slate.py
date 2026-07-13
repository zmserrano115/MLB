"""Read-only game slate and persisted weather use cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Generic, TypeVar

from all_rise.application.operations import CacheProbe
from all_rise.cache.versioned import versioned_key
from all_rise.repositories.protocols import GameRecord, GameWeatherRecord, SlateRepository

RecordT = TypeVar("RecordT", GameRecord, GameWeatherRecord)


@dataclass(frozen=True, slots=True)
class SlateResult(Generic[RecordT]):
    records: list[RecordT]
    data_version: str
    cache_outcome: str
    stale: bool
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class SlateItemResult(Generic[RecordT]):
    record: RecordT | None
    data_version: str
    cache_outcome: str
    stale: bool


class SlateService:
    def __init__(
        self,
        repository: SlateRepository,
        cache: CacheProbe,
        *,
        cache_ttl_seconds: int = 30,
        negative_ttl_seconds: int = 5,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._negative_ttl_seconds = negative_ttl_seconds

    def games(
        self,
        *,
        game_date: str,
        team: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> SlateResult[GameRecord]:
        data_version = self._version()
        key = self._key("games", (game_date, team, status, limit, cursor), data_version)
        result = self._cache.get_or_load(
            key,
            lambda: [
                asdict(record)
                for record in self._repository.get_games(
                    game_date=game_date,
                    team=team,
                    status=status,
                    limit=limit + 1,
                    cursor=cursor,
                )
            ],
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        rows = result.value if isinstance(result.value, list) else []
        records = [GameRecord(**row) for row in rows[:limit]]
        next_cursor = records[-1].game_id if len(rows) > limit and records else None
        return SlateResult(records, data_version, result.outcome.value, result.stale, next_cursor)

    def game(self, game_id: str) -> SlateItemResult[GameRecord]:
        data_version = self._version()
        key = self._key("game", (game_id,), data_version)
        result = self._cache.get_or_load(
            key,
            lambda: (
                asdict(record) if (record := self._repository.get_game(game_id)) else None
            ),
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        record = GameRecord(**result.value) if isinstance(result.value, dict) else None
        return SlateItemResult(record, data_version, result.outcome.value, result.stale)

    def weather(
        self,
        *,
        game_date: str,
        game_id: str | None,
        limit: int,
    ) -> SlateResult[GameWeatherRecord]:
        data_version = self._version()
        key = self._key("weather", (game_date, game_id, limit), data_version)
        result = self._cache.get_or_load(
            key,
            lambda: [
                asdict(record)
                for record in self._repository.get_weather(
                    game_date=game_date,
                    game_id=game_id,
                    limit=limit,
                )
            ],
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        rows = result.value if isinstance(result.value, list) else []
        records = [GameWeatherRecord(**row) for row in rows]
        return SlateResult(records, data_version, result.outcome.value, result.stale)

    def game_weather(self, game_id: str) -> SlateItemResult[GameWeatherRecord]:
        data_version = self._version()
        key = self._key("game-weather", (game_id,), data_version)
        result = self._cache.get_or_load(
            key,
            lambda: (
                asdict(record)
                if (record := self._repository.get_game_weather(game_id))
                else None
            ),
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        record = GameWeatherRecord(**result.value) if isinstance(result.value, dict) else None
        return SlateItemResult(record, data_version, result.outcome.value, result.stale)

    def _version(self) -> str:
        raw = self._repository.get_data_version()
        return sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _key(namespace: str, parts: tuple[object, ...], version: str) -> str:
        fingerprint = sha256(repr(parts).encode("utf-8")).hexdigest()[:16]
        return versioned_key(namespace, [fingerprint], version)
