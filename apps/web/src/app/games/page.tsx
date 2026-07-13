import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";

import { DateFilter } from "../../components/date-filter";
import { GameCard } from "../../components/game-card";
import { LegacyFallback } from "../../components/legacy-fallback";
import { getGames } from "../../lib/api";
import { canonicalDate, displayDate, safeFilter } from "../../lib/date-state";
import { buildLegacyUrl, resolveLegacyRoute } from "../../lib/route-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Games" };

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function GamesPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const date = canonicalDate(query.date);
  const team = safeFilter(query.team, 5).toUpperCase();
  const status = safeFilter(query.status);
  const result = await getGames({ date, team: team || undefined, status: status || undefined });
  const games = result.ok ? result.value.data : [];
  const legacyUrl = buildLegacyUrl(
    process.env.LEGACY_BASE_URL || "http://localhost:8501/",
    resolveLegacyRoute(["games"])!,
    { date, ...(team ? { team } : {}), ...(status ? { status } : {}) },
  );

  return (
    <main id="main-content" className="page-stack slate-page">
      <PageHeader
        eyebrow="Daily slate"
        title="Games"
        summary={`${displayDate(date)} — schedules, probable pitchers, scores, and game context.`}
      >
        <StatusPill tone={result.ok && result.value.meta.stale ? "warning" : "healthy"}>
          {result.ok && result.value.meta.stale ? "Stale snapshot" : "Persisted data"}
        </StatusPill>
        <LegacyFallback href={legacyUrl} label="complete Games" />
      </PageHeader>

      <DateFilter action="/games" date={date} team={team} status={status} showGameFilters />

      {!result.ok ? (
        <Panel className="state-panel" labelledBy="games-error-heading">
          <p className="panel-kicker">Slate unavailable</p>
          <h2 id="games-error-heading">The persisted schedule could not be loaded.</h2>
          <p>{result.message} The complete existing view remains available.</p>
          <LegacyFallback href={legacyUrl} label="Games" />
        </Panel>
      ) : games.length === 0 ? (
        <Panel className="state-panel" labelledBy="games-empty-heading">
          <p className="panel-kicker">No published games</p>
          <h2 id="games-empty-heading">No schedule snapshot matches these filters.</h2>
          <p>
            The worker has not published a matching slate yet, or no games are scheduled. Nothing
            is fetched from a provider during this page request.
          </p>
          <LegacyFallback href={legacyUrl} label="complete Games" />
        </Panel>
      ) : (
        <section className="game-grid" aria-label={`Games for ${date}`}>
          {games.map((game) => <GameCard game={game} key={game.game_id} />)}
        </section>
      )}
    </main>
  );
}
