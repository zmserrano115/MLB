import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { LegacyFallback } from "../../../components/legacy-fallback";
import { LiveGameCenter } from "../../../components/live-game-center";
import { getGame, getGameWeather, getLiveGame } from "../../../lib/api";
import { canonicalDate } from "../../../lib/date-state";
import { buildLegacyUrl, resolveLegacyRoute } from "../../../lib/route-state";

export const dynamic = "force-dynamic";
type Tab = "live" | "stats" | "box-score";
type PageProps = { params: Promise<{ gameId: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

function decodeRouteSegment(value: string) { try { return decodeURIComponent(value); } catch { return value; } }
function tabValue(value: string | string[] | undefined): Tab { return value === "stats" || value === "box-score" ? value : "live"; }

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  return { title: `Game ${decodeRouteSegment((await params).gameId)}` };
}

export default async function GameDetailPage({ params, searchParams }: PageProps) {
  const gameId = decodeRouteSegment((await params).gameId);
  const query = await searchParams;
  const date = canonicalDate(query.date);
  const [gameResult, weatherResult, liveResult] = await Promise.all([getGame(gameId), getGameWeather(gameId), getLiveGame(gameId)]);
  const legacyUrl = buildLegacyUrl(process.env.LEGACY_BASE_URL || "http://localhost:8501/", resolveLegacyRoute(["games", gameId])!, { date, game_pk: gameId.replace(/^mlb:/, "") });
  const liveEnabled = process.env.LIVE_GAME_CENTER_ENABLED !== "false";
  const fallbackEnabled = process.env.LIVE_LEGACY_FALLBACK_ENABLED !== "false";

  if (!gameResult.ok) return <main id="main-content" className="page-stack"><PageHeader eyebrow="Game detail" title="Game data unavailable" summary="This game is not present in the persisted read model yet." /><Panel className="state-panel" labelledBy="game-unavailable-heading"><h2 id="game-unavailable-heading">Game snapshot unavailable</h2><p>{gameResult.message}</p><div className="handoff-actions">{fallbackEnabled && <LegacyFallback href={legacyUrl} label="Game Center" />}<Link className="button button--secondary" href={`/games?date=${date}`}>Back to games</Link></div></Panel></main>;

  const game = gameResult.value.data;
  const weather = weatherResult.ok ? weatherResult.value.data : null;
  const publicApi = (process.env.NEXT_PUBLIC_API_BASE_URL || process.env.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
  return <main id="main-content" className="page-stack game-detail-page">
    <PageHeader eyebrow={game.status || "Game"} title={`${game.away_team.abbreviation || game.away_team.name} at ${game.home_team.abbreviation || game.home_team.name}`} summary={`${game.venue?.name || "Venue TBD"} — ${game.game_date}`}>
      <StatusPill tone={gameResult.value.meta.stale ? "warning" : "healthy"}>{gameResult.value.meta.stale ? "Stale snapshot" : "Persisted snapshot"}</StatusPill>
    </PageHeader>

    {liveEnabled && liveResult.ok ? <LiveGameCenter initial={liveResult.value.data} initialStale={liveResult.value.meta.stale} endpoint={`${publicApi}/api/v1/games/${encodeURIComponent(gameId)}/live`} initialTab={tabValue(query.tab)} /> : <Panel className="state-panel" labelledBy="live-unavailable-heading"><p className="panel-kicker">Live Game Center</p><h2 id="live-unavailable-heading">{liveEnabled ? "Awaiting the first worker snapshot" : "React Game Center is disabled"}</h2><p>{liveResult.ok ? "The persisted schedule remains available below." : liveResult.message}</p>{fallbackEnabled && <LegacyFallback href={legacyUrl} label="legacy Game Center" />}</Panel>}

    <section className="detail-grid" aria-label="Game context">
      <Panel labelledBy="pitchers-heading"><p className="panel-kicker">Probable pitchers</p><h2 id="pitchers-heading">Starting matchup</h2><dl className="detail-list"><div><dt>{game.away_team.abbreviation || "Away"}</dt><dd>{game.away_probable_pitcher?.name || "TBD"}</dd></div><div><dt>{game.home_team.abbreviation || "Home"}</dt><dd>{game.home_probable_pitcher?.name || "TBD"}</dd></div></dl></Panel>
      <Panel labelledBy="weather-heading"><p className="panel-kicker">Weather context</p><h2 id="weather-heading">{weather?.available ? weather.condition || "Forecast" : "Awaiting snapshot"}</h2>{weather?.available ? <dl className="detail-list"><div><dt>Temperature</dt><dd>{weather.temperature_f?.toFixed(0) ?? "—"}°F</dd></div><div><dt>Wind</dt><dd>{weather.wind_speed_mph?.toFixed(0) ?? "—"} mph</dd></div><div><dt>Run environment</dt><dd>{weather.edge_label || "Neutral"}</dd></div></dl> : <p>No persisted forecast is available. The page will not invent one.</p>}</Panel>
    </section>
    <div className="handoff-actions"><Link className="button button--primary" href={`/games?date=${game.game_date}`}>Back to slate</Link>{fallbackEnabled && <LegacyFallback href={legacyUrl} label="legacy Game Center" />}</div>
  </main>;
}
