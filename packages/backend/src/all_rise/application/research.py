"""Cached player profile and batter-versus-pitcher research use cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, cast

from all_rise.application.operations import CacheProbe
from all_rise.cache.versioned import versioned_key
from all_rise.repositories.protocols import (
    BatterPitcherMatchupRecord,
    BattingSummaryRecord,
    PitchingSummaryRecord,
    PlayerGameLogRecord,
    PlayerRecord,
    ResearchRepository,
)


@dataclass(frozen=True, slots=True)
class PlayerDirectoryResult:
    records: list[PlayerRecord]
    data_version: str
    cache_outcome: str
    stale: bool
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerProfileResult:
    player: PlayerRecord | None
    batting: BattingSummaryRecord | None
    pitching: PitchingSummaryRecord | None
    game_logs: list[PlayerGameLogRecord]
    data_version: str
    cache_outcome: str
    stale: bool


@dataclass(frozen=True, slots=True)
class MatchupResult:
    matchup: BatterPitcherMatchupRecord | None
    game_logs: list[PlayerGameLogRecord]
    data_version: str
    cache_outcome: str
    stale: bool


class ResearchService:
    def __init__(
        self,
        repository: ResearchRepository,
        cache: CacheProbe,
        *,
        cache_ttl_seconds: int = 30,
        negative_ttl_seconds: int = 5,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._negative_ttl_seconds = negative_ttl_seconds

    def players(
        self,
        *,
        query: str | None,
        role: str | None,
        season: int | None,
        limit: int,
        cursor: str | None,
    ) -> PlayerDirectoryResult:
        version = self._version()
        key = self._key("players", (query, role, season, limit, cursor), version)
        cached = self._cache.get_or_load(
            key,
            lambda: [
                asdict(record)
                for record in self._repository.get_players(
                    query=query,
                    role=role,
                    season=season,
                    limit=limit + 1,
                    cursor=cursor,
                )
            ],
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        rows = cached.value if isinstance(cached.value, list) else []
        records = [PlayerRecord(**row) for row in rows[:limit]]
        next_cursor = records[-1].player_id if len(rows) > limit and records else None
        return PlayerDirectoryResult(
            records, version, cached.outcome.value, cached.stale, next_cursor
        )

    def player_profile(
        self,
        player_id: str,
        *,
        season: int | None,
        group: str,
        limit: int,
    ) -> PlayerProfileResult:
        version = self._version()
        key = self._key("player-profile", (player_id, season, group, limit), version)

        def load() -> dict[str, object]:
            player = self._repository.get_player(player_id)
            if not player:
                return {"player": None, "batting": None, "pitching": None, "logs": []}
            batting = self._repository.get_player_batting_summary(player_id, season=season)
            pitching = self._repository.get_player_pitching_summary(player_id, season=season)
            logs = self._repository.get_player_game_logs(
                player_id, season=season, group=group, limit=limit
            )
            return {
                "player": asdict(player),
                "batting": asdict(batting) if batting else None,
                "pitching": asdict(pitching) if pitching else None,
                "logs": [asdict(log) for log in logs],
            }

        cached = self._cache.get_or_load(
            key,
            load,
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        value = cached.value if isinstance(cached.value, dict) else {}
        player = PlayerRecord(**value["player"]) if isinstance(value.get("player"), dict) else None
        batting = (
            BattingSummaryRecord(**value["batting"])
            if isinstance(value.get("batting"), dict)
            else None
        )
        pitching = (
            PitchingSummaryRecord(**value["pitching"])
            if isinstance(value.get("pitching"), dict)
            else None
        )
        raw_logs = value.get("logs")
        rows = cast(list[dict[str, Any]], raw_logs) if isinstance(raw_logs, list) else []
        logs = [PlayerGameLogRecord(**row) for row in rows]
        return PlayerProfileResult(
            player, batting, pitching, logs, version, cached.outcome.value, cached.stale
        )

    def batter_pitcher_matchup(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
        limit: int,
    ) -> MatchupResult:
        version = self._version()
        key = self._key("bvp", (batter_id, pitcher_id, season, limit), version)

        def load() -> dict[str, object]:
            matchup = self._repository.get_batter_pitcher_matchup(
                batter_id=batter_id, pitcher_id=pitcher_id, season=season
            )
            logs = (
                self._repository.get_batter_pitcher_logs(
                    batter_id=batter_id,
                    pitcher_id=pitcher_id,
                    season=season,
                    limit=limit,
                )
                if matchup
                else []
            )
            return {
                "matchup": asdict(matchup) if matchup else None,
                "logs": [asdict(log) for log in logs],
            }

        cached = self._cache.get_or_load(
            key,
            load,
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        value = cached.value if isinstance(cached.value, dict) else {}
        matchup = (
            BatterPitcherMatchupRecord(**value["matchup"])
            if isinstance(value.get("matchup"), dict)
            else None
        )
        raw_logs = value.get("logs")
        rows = cast(list[dict[str, Any]], raw_logs) if isinstance(raw_logs, list) else []
        logs = [PlayerGameLogRecord(**row) for row in rows]
        return MatchupResult(matchup, logs, version, cached.outcome.value, cached.stale)

    def _version(self) -> str:
        return sha256(self._repository.get_data_version().encode()).hexdigest()[:16]

    @staticmethod
    def _key(namespace: str, parts: tuple[object, ...], version: str) -> str:
        fingerprint = sha256(repr(parts).encode()).hexdigest()[:16]
        return versioned_key(namespace, [fingerprint], version)
