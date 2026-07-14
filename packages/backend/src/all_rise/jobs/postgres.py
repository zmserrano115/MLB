from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from all_rise.jobs.contracts import (
    ArtifactRecord,
    ClaimResult,
    ClaimState,
    TaskRequest,
    TaskResult,
)
from all_rise.models import (
    DataSourceStatus,
    Game,
    LiveGameEvent,
    LiveGameSnapshot,
    Player,
    ProcessingCheckpoint,
    RefreshRun,
    RefreshRunItem,
    SourceArtifact,
    Team,
    Venue,
    WeatherSnapshot,
)


class PostgresJobStore:
    """Transactional PostgreSQL authority for task execution and publication."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 2,
        max_overflow: int = 2,
    ) -> None:
        self._engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def claim(
        self,
        request: TaskRequest,
        *,
        now: datetime,
        stale_after_seconds: int,
    ) -> ClaimResult:
        values = {
            "idempotency_key": request.idempotency_key,
            "task_name": request.task_name,
            "source": request.source,
            "scope": request.scope,
            "status": "running",
            "attempt": 1,
            "max_attempts": request.max_attempts,
            "games_checked": 0,
            "games_processed": 0,
            "facts_loaded": 0,
            "input_payload": request.payload,
            "created_at": now,
            "started_at": now,
            "heartbeat_at": now,
        }
        with self._sessions.begin() as session:
            created_id = session.execute(
                insert(RefreshRun)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[RefreshRun.idempotency_key])
                .returning(RefreshRun.id)
            ).scalar_one_or_none()
            if created_id is not None:
                return ClaimResult(ClaimState.ACQUIRED, int(created_id), 1)

            run = session.execute(
                select(RefreshRun)
                .where(RefreshRun.idempotency_key == request.idempotency_key)
                .with_for_update()
            ).scalar_one()
            if run.task_name != request.task_name or run.input_payload != request.payload:
                raise ValueError("idempotency key was reused for a different task or payload")
            if run.status == "succeeded":
                return ClaimResult(ClaimState.DUPLICATE, run.id, run.attempt)
            fresh_cutoff = now - timedelta(seconds=stale_after_seconds)
            if run.status == "running" and run.heartbeat_at and run.heartbeat_at >= fresh_cutoff:
                return ClaimResult(ClaimState.IN_PROGRESS, run.id, run.attempt)
            if run.next_retry_at and run.next_retry_at > now:
                return ClaimResult(ClaimState.IN_PROGRESS, run.id, run.attempt)
            if run.attempt >= run.max_attempts or run.status == "dead_letter":
                run.status = "dead_letter"
                run.dead_lettered_at = run.dead_lettered_at or now
                return ClaimResult(ClaimState.DEAD_LETTER, run.id, run.attempt)

            run.status = "running"
            run.attempt += 1
            run.started_at = now
            run.heartbeat_at = now
            run.next_retry_at = None
            run.completed_at = None
            run.error_code = None
            run.message = None
            return ClaimResult(ClaimState.ACQUIRED, run.id, run.attempt)

    def heartbeat(self, run_id: int, attempt: int, *, now: datetime) -> bool:
        with self._sessions.begin() as session:
            run = session.get(RefreshRun, run_id, with_for_update=True)
            if run is None or run.status != "running" or run.attempt != attempt:
                return False
            run.heartbeat_at = now
            return True

    def record_item(
        self,
        run_id: int,
        attempt: int,
        *,
        item_key: str,
        status: str,
        payload: dict[str, object],
        error_code: str | None,
        message: str | None,
        now: datetime,
    ) -> None:
        completed_at = now if status in {"succeeded", "failed", "skipped"} else None
        statement = insert(RefreshRunItem).values(
            run_id=run_id,
            item_key=item_key,
            status=status,
            attempt=attempt,
            error_code=error_code,
            message=message,
            payload=payload,
            created_at=now,
            completed_at=completed_at,
        )
        with self._sessions.begin() as session:
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        RefreshRunItem.run_id,
                        RefreshRunItem.item_key,
                        RefreshRunItem.attempt,
                    ],
                    set_={
                        "status": status,
                        "error_code": error_code,
                        "message": message,
                        "payload": payload,
                        "completed_at": completed_at,
                    },
                )
            )

    def register_artifact(self, artifact: ArtifactRecord) -> None:
        statement = (
            insert(SourceArtifact)
            .values(
                source=artifact.source,
                generation=artifact.generation,
                uri=artifact.uri,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                fetched_at=artifact.fetched_at,
                source_version=artifact.source_version,
                inventory=artifact.inventory,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    SourceArtifact.source,
                    SourceArtifact.generation,
                    SourceArtifact.sha256,
                ]
            )
        )
        with self._sessions.begin() as session:
            session.execute(statement)

    def succeed(
        self,
        run_id: int,
        attempt: int,
        result: TaskResult,
        *,
        now: datetime,
    ) -> None:
        with self._sessions.begin() as session:
            run = self._owned_run(session, run_id, attempt)
            run.status = "succeeded"
            run.games_processed = result.processed_items
            run.facts_loaded = result.facts_loaded
            run.result_payload = result.payload
            run.completed_at = now
            run.heartbeat_at = now
            if result.publication is not None:
                publication = result.publication
                self._publish_dataset(session, publication.dataset, publication.records, now)
                checkpoint = insert(ProcessingCheckpoint).values(
                    source=publication.source,
                    scope=publication.scope,
                    watermark=publication.watermark,
                    source_version=publication.source_version,
                    updated_at=now,
                )
                session.execute(
                    checkpoint.on_conflict_do_update(
                        index_elements=[
                            ProcessingCheckpoint.source,
                            ProcessingCheckpoint.scope,
                        ],
                        set_={
                            "watermark": publication.watermark,
                            "source_version": publication.source_version,
                            "updated_at": now,
                        },
                    )
                )
                status = insert(DataSourceStatus).values(
                    source=publication.source,
                    watermark=publication.watermark,
                    freshness_status="fresh",
                    last_success_at=now,
                    detail=publication.detail,
                )
                session.execute(
                    status.on_conflict_do_update(
                        index_elements=[DataSourceStatus.source],
                        set_={
                            "watermark": publication.watermark,
                            "freshness_status": "fresh",
                            "last_success_at": now,
                            "detail": publication.detail,
                        },
                    )
                )
                run.published_at = now

    @classmethod
    def _publish_dataset(
        cls,
        session: Session,
        dataset: str | None,
        records: tuple[dict[str, Any], ...],
        now: datetime,
    ) -> None:
        if dataset is None:
            if records:
                raise ValueError("publication records require a dataset")
            return
        if dataset == "schedule":
            cls._publish_schedule(session, records, now)
            return
        if dataset == "weather":
            cls._publish_weather(session, records)
            return
        if dataset == "live_game":
            cls._publish_live_game(session, records)
            return
        raise ValueError(f"unsupported publication dataset: {dataset}")

    @classmethod
    def _publish_schedule(
        cls,
        session: Session,
        records: tuple[dict[str, Any], ...],
        now: datetime,
    ) -> None:
        for record in records:
            source_version = str(record["source_version"])[:64]
            away_team = cls._upsert_team(session, record["away_team"], source_version, now)
            home_team = cls._upsert_team(session, record["home_team"], source_version, now)
            venue = cls._upsert_venue(session, record.get("venue"), now)
            away_pitcher = cls._upsert_player(session, record.get("away_probable_pitcher"), now)
            home_pitcher = cls._upsert_player(session, record.get("home_probable_pitcher"), now)
            game_pk = int(record["mlb_game_pk"])
            source_game_id = str(record["source_game_id"])
            game = session.execute(
                select(Game).where(
                    or_(Game.mlb_game_pk == game_pk, Game.source_game_id == source_game_id)
                )
            ).scalar_one_or_none()
            values = {
                "source_game_id": source_game_id,
                "mlb_game_pk": game_pk,
                "legacy_game_pk": game_pk,
                "source": "mlb-statsapi",
                "source_version": source_version,
                "game_date": _date(record["game_date"]),
                "season": int(record.get("season") or _date(record["game_date"]).year),
                "game_time_utc": _datetime(record.get("game_time_utc")),
                "away_team_id": away_team.id,
                "home_team_id": home_team.id,
                "venue_id": venue.id if venue else None,
                "away_probable_pitcher_id": away_pitcher.id if away_pitcher else None,
                "home_probable_pitcher_id": home_pitcher.id if home_pitcher else None,
                "game_status": _text(record.get("game_status")),
                "away_score": _integer(record.get("away_score")),
                "home_score": _integer(record.get("home_score")),
                "source_updated_at": now,
            }
            if game is None:
                session.add(Game(**values))
            else:
                for key, value in values.items():
                    setattr(game, key, value)

    @staticmethod
    def _upsert_team(
        session: Session,
        record: dict[str, Any],
        source_version: str,
        now: datetime,
    ) -> Team:
        provider_id = int(record["provider_team_id"])
        abbreviation = _text(record.get("abbreviation"))
        team = session.execute(
            select(Team).where(Team.provider_team_id == provider_id)
        ).scalar_one_or_none()
        if team is None and abbreviation:
            team = session.execute(
                select(Team).where(Team.abbreviation == abbreviation)
            ).scalar_one_or_none()
        if team is None:
            team = Team(
                source_key=f"mlb-team:{provider_id}",
                abbreviation=abbreviation,
                provider_team_id=provider_id,
                name=str(record["name"]),
                source_version=source_version,
                updated_at=now,
            )
            session.add(team)
            session.flush()
            return team
        if team.provider_team_id not in {None, provider_id}:
            raise ValueError(f"team identity conflict for {abbreviation or provider_id}")
        team.provider_team_id = provider_id
        team.abbreviation = abbreviation or team.abbreviation
        team.name = str(record["name"])
        team.source_version = source_version
        team.updated_at = now
        session.flush()
        return team

    @staticmethod
    def _upsert_venue(
        session: Session, record: dict[str, Any] | None, now: datetime
    ) -> Venue | None:
        if not record or record.get("provider_venue_id") is None:
            return None
        provider_id = int(record["provider_venue_id"])
        venue = session.execute(
            select(Venue).where(Venue.provider_venue_id == provider_id)
        ).scalar_one_or_none()
        values = {
            "provider_venue_id": provider_id,
            "name": str(record.get("name") or "Venue TBD"),
            "city": _text(record.get("city")),
            "latitude": record.get("latitude"),
            "longitude": record.get("longitude"),
            "elevation_ft": record.get("elevation_ft"),
            "roof_type": _text(record.get("roof_type")),
            "center_field_azimuth": record.get("center_field_azimuth"),
            "source_updated_at": now,
        }
        if venue is None:
            venue = Venue(**values)
            session.add(venue)
        else:
            for key, value in values.items():
                setattr(venue, key, value)
        session.flush()
        return venue

    @staticmethod
    def _upsert_player(
        session: Session, record: dict[str, Any] | None, now: datetime
    ) -> Player | None:
        if not record or record.get("provider_player_id") is None:
            return None
        provider_id = int(record["provider_player_id"])
        player = session.execute(
            select(Player).where(Player.provider_player_id == provider_id)
        ).scalar_one_or_none()
        if player is None:
            player = Player(
                provider_player_id=provider_id,
                name=_text(record.get("name")),
                active_status="active",
                source_updated_at=now,
            )
            session.add(player)
        else:
            player.name = _text(record.get("name")) or player.name
            player.active_status = "active"
            player.source_updated_at = now
        session.flush()
        return player

    @staticmethod
    def _publish_weather(session: Session, records: tuple[dict[str, Any], ...]) -> None:
        for record in records:
            game = session.execute(
                select(Game).where(Game.source_game_id == str(record["source_game_id"]))
            ).scalar_one_or_none()
            if game is None:
                raise ValueError(f"unknown game for weather: {record['source_game_id']}")
            observed_at = _datetime(record["observed_at"])
            if observed_at is None:
                raise ValueError("weather observed_at is required")
            source = str(record["source"])
            snapshot = session.execute(
                select(WeatherSnapshot).where(
                    WeatherSnapshot.game_id == game.id,
                    WeatherSnapshot.observed_at == observed_at,
                    WeatherSnapshot.source == source,
                )
            ).scalar_one_or_none()
            values = {
                "game_id": game.id,
                "observed_at": observed_at,
                "forecast_for": _datetime(record.get("forecast_for")),
                "source": source,
                "source_version": _text(record.get("source_version")),
                "condition": _text(record.get("condition")),
                "temperature_f": record.get("temperature_f"),
                "feels_like_f": record.get("feels_like_f"),
                "humidity_percent": record.get("humidity_percent"),
                "wind_speed_mph": record.get("wind_speed_mph"),
                "wind_direction_degrees": record.get("wind_direction_degrees"),
                "wind_out_mph": record.get("wind_out_mph"),
                "precipitation_probability": record.get("precipitation_probability"),
                "hitter_adjustment": record.get("hitter_adjustment"),
                "pitcher_adjustment": record.get("pitcher_adjustment"),
                "edge_label": _text(record.get("edge_label")),
                "stale": bool(record.get("stale", False)),
                "provider_residual": record.get("provider_residual"),
            }
            if snapshot is None:
                session.add(WeatherSnapshot(**values))
            else:
                for key, value in values.items():
                    setattr(snapshot, key, value)

    @staticmethod
    def _publish_live_game(session: Session, records: tuple[dict[str, Any], ...]) -> None:
        for record in records:
            game = session.execute(
                select(Game).where(Game.source_game_id == str(record["game_id"]))
            ).scalar_one_or_none()
            if game is None:
                raise ValueError(f"unknown game for live snapshot: {record['game_id']}")
            observed_at = _datetime(record["observed_at"])
            if observed_at is None:
                raise ValueError("live observed_at is required")
            values = {
                "game_id": game.id,
                "version": str(record["version"]),
                "observed_at": observed_at,
                "feed_timestamp": _text(record.get("feed_timestamp")),
                "abstract_state": str(record["abstract_state"]),
                "detailed_state": str(record["detailed_state"]),
                "is_final": bool(record["is_final"]),
                "payload_size_bytes": int(record["payload_size_bytes"]),
                "snapshot": record["snapshot"],
            }
            statement = insert(LiveGameSnapshot).values(**values)
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[LiveGameSnapshot.game_id, LiveGameSnapshot.version],
                    set_={key: value for key, value in values.items() if key != "game_id"},
                )
            )
            snapshot = record["snapshot"]
            teams = snapshot.get("teams", {})
            game.game_status = str(record["detailed_state"])
            game.away_score = _integer(teams.get("away", {}).get("runs"))
            game.home_score = _integer(teams.get("home", {}).get("runs"))
            game.source_updated_at = observed_at
            for event in record.get("events", []):
                event_values = {
                    "game_id": game.id,
                    "event_key": str(event["event_key"]),
                    "sequence": int(event["sequence"]),
                    "inning": _integer(event.get("inning")),
                    "half_inning": _text(event.get("half_inning")),
                    "event_type": str(event["event_type"]),
                    "description": _text(event.get("description")),
                    "payload": event.get("payload") or {},
                    "source_updated_at": _datetime(event.get("source_updated_at")),
                }
                event_statement = insert(LiveGameEvent).values(**event_values)
                session.execute(
                    event_statement.on_conflict_do_update(
                        index_elements=[LiveGameEvent.game_id, LiveGameEvent.event_key],
                        set_={
                            key: value
                            for key, value in event_values.items()
                            if key not in {"game_id", "event_key"}
                        },
                    )
                )

    def fail(
        self,
        run_id: int,
        attempt: int,
        *,
        error_code: str,
        message: str,
        retryable: bool,
        next_retry_at: datetime | None,
        now: datetime,
    ) -> bool:
        with self._sessions.begin() as session:
            run = self._owned_run(session, run_id, attempt)
            can_retry = retryable and attempt < run.max_attempts
            run.status = "retry" if can_retry else "dead_letter"
            run.error_code = error_code[:96]
            run.message = message[:2_000]
            run.completed_at = now
            run.heartbeat_at = now
            run.next_retry_at = next_retry_at if can_retry else None
            if not can_retry:
                run.dead_lettered_at = now
            status = insert(DataSourceStatus).values(
                source=run.source,
                freshness_status="degraded",
                last_failure_at=now,
                detail=run.message,
            )
            session.execute(
                status.on_conflict_do_update(
                    index_elements=[DataSourceStatus.source],
                    set_={
                        "freshness_status": "degraded",
                        "last_failure_at": now,
                        "detail": run.message,
                    },
                )
            )
            return can_retry

    def recover_stale(self, *, now: datetime, stale_after_seconds: int) -> int:
        cutoff = now - timedelta(seconds=stale_after_seconds)
        recovered = 0
        with self._sessions.begin() as session:
            runs = session.execute(
                select(RefreshRun)
                .where(RefreshRun.status == "running", RefreshRun.heartbeat_at < cutoff)
                .with_for_update(skip_locked=True)
            ).scalars()
            for run in runs:
                recovered += 1
                if run.attempt < run.max_attempts:
                    run.status = "retry"
                    run.next_retry_at = now
                    run.error_code = "stale_heartbeat"
                    run.message = "Recovered after heartbeat timeout"
                else:
                    run.status = "dead_letter"
                    run.dead_lettered_at = now
                    run.error_code = "stale_heartbeat"
                    run.message = "Heartbeat timeout exhausted attempts"
                run.completed_at = now
        return recovered

    @staticmethod
    def _owned_run(session: Session, run_id: int, attempt: int) -> RefreshRun:
        run = session.get(RefreshRun, run_id, with_for_update=True)
        if run is None or run.status != "running" or run.attempt != attempt:
            raise RuntimeError("task execution lease is no longer owned")
        return run

    def close(self) -> None:
        self._engine.dispose()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(value: Any) -> int | None:
    return int(value) if value is not None else None


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
