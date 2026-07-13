import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { LegacyFallback } from "../../../components/legacy-fallback";
import { getGame, getGameWeather } from "../../../lib/api";
import { canonicalDate } from "../../../lib/date-state";
import { buildLegacyUrl, resolveLegacyRoute } from "../../../lib/route-state";

export const dynamic = "force-dynamic";

type PageProps = {
  params: Promise<{ gameId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function decodeRouteSegment(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  return { title: `Game ${decodeRouteSegment((await params).gameId)}` };
}

export default async function GameDetailPage({ params, searchParams }: PageProps) {
  const gameId = decodeRouteSegment((await params).gameId);
  const date = canonicalDate((await searchParams).date);
  const [gameResult, weatherResult] = await Promise.all([
    getGame(gameId),
    getGameWeather(gameId),
  ]);
  const legacyUrl = buildLegacyUrl(
    process.env.LEGACY_BASE_URL || "http://localhost:8501/",
    resolveLegacyRoute(["games", gameId])!,
    { date, game_pk: gameId.replace(/^mlb:/, "") },
  );

  if (!gameResult.ok) {
    return (
      <main id="main-content" className="page-stack">
        <PageHeader
          eyebrow="Game detail"
          title="Game data unavailable"
          summary="This game is not present in the persisted read model yet."
        />
        <Panel className="state-panel" labelledBy="game-unavailable-heading">
          <h2 id="game-unavailable-heading">Continue in the existing Game Center</h2>
          <p>{gameResult.message}</p>
          <div className="handoff-actions">
            <LegacyFallback href={legacyUrl} label="Game Center" />
            <Link className="button button--secondary" href={`/games?date=${date}`}>Back to games</Link>
          </div>
        </Panel>
      </main>
    );
  }

  const game = gameResult.value.data;
  const weather = weatherResult.ok ? weatherResult.value.data : null;
  return (
    <main id="main-content" className="page-stack game-detail-page">
      <PageHeader
        eyebrow={game.status || "Game"}
        title={`${game.away_team.abbreviation || game.away_team.name} at ${game.home_team.abbreviation || game.home_team.name}`}
        summary={`${game.venue?.name || "Venue TBD"} — ${game.game_date}`}
      >
        <StatusPill tone={gameResult.value.meta.stale ? "warning" : "healthy"}>
          {gameResult.value.meta.stale ? "Stale snapshot" : "Persisted snapshot"}
        </StatusPill>
      </PageHeader>

      <Panel className="scoreboard-panel" labelledBy="scoreboard-heading">
        <h2 id="scoreboard-heading" className="sr-only">Scoreboard</h2>
        <div className="scoreboard-team">
          <span>Away</span><strong>{game.away_team.name}</strong><b>{game.away_team.score ?? "—"}</b>
        </div>
        <div className="scoreboard-divider">at</div>
        <div className="scoreboard-team">
          <span>Home</span><strong>{game.home_team.name}</strong><b>{game.home_team.score ?? "—"}</b>
        </div>
      </Panel>

      <section className="detail-grid" aria-label="Game context">
        <Panel labelledBy="pitchers-heading">
          <p className="panel-kicker">Probable pitchers</p>
          <h2 id="pitchers-heading">Starting matchup</h2>
          <dl className="detail-list">
            <div><dt>{game.away_team.abbreviation || "Away"}</dt><dd>{game.away_probable_pitcher?.name || "TBD"}</dd></div>
            <div><dt>{game.home_team.abbreviation || "Home"}</dt><dd>{game.home_probable_pitcher?.name || "TBD"}</dd></div>
          </dl>
        </Panel>
        <Panel labelledBy="weather-heading">
          <p className="panel-kicker">Weather context</p>
          <h2 id="weather-heading">{weather?.available ? weather.condition || "Forecast" : "Awaiting snapshot"}</h2>
          {weather?.available ? (
            <dl className="detail-list">
              <div><dt>Temperature</dt><dd>{weather.temperature_f?.toFixed(0) ?? "—"}°F</dd></div>
              <div><dt>Wind</dt><dd>{weather.wind_speed_mph?.toFixed(0) ?? "—"} mph</dd></div>
              <div><dt>Run environment</dt><dd>{weather.edge_label || "Neutral"}</dd></div>
            </dl>
          ) : (
            <p>No persisted forecast is available. The page will not invent one.</p>
          )}
        </Panel>
      </section>

      <div className="handoff-actions">
        <Link className="button button--primary" href={`/games?date=${game.game_date}`}>Back to slate</Link>
        <LegacyFallback href={legacyUrl} label="full Game Center" />
      </div>
    </main>
  );
}
