import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { LegacyFallback } from "../../components/legacy-fallback";
import { getPlayers } from "../../lib/api";
import { safeFilter } from "../../lib/date-state";
import { safeRole, safeSeason } from "../../lib/research-state";
import { buildLegacyUrl, resolveLegacyRoute } from "../../lib/route-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Players" };

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PlayersPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const query = safeFilter(params.query, 80);
  const role = safeRole(params.role);
  const season = safeSeason(params.season);
  const result = await getPlayers({
    query: query || undefined,
    role,
    season,
  });
  const players = result.ok ? result.value.data : [];
  const legacyState = {
    ...(season ? { season: String(season) } : {}),
    ...(query ? { query } : {}),
  };
  const legacyUrl = buildLegacyUrl(
    process.env.LEGACY_BASE_URL || "http://localhost:8501/",
    resolveLegacyRoute(["players"])!,
    legacyState,
  );

  return (
    <main id="main-content" className="page-stack research-page">
      <PageHeader
        eyebrow="Player research"
        title="Players"
        summary="Find a player, open a durable profile, and keep season and role filters in the URL."
      >
        <StatusPill tone={result.ok && result.value.meta.stale ? "warning" : "healthy"}>
          {result.ok && result.value.meta.stale ? "Stale snapshot" : "Persisted stats"}
        </StatusPill>
        <LegacyFallback href={legacyUrl} label="complete Players" />
      </PageHeader>

      <form className="filter-bar research-filter" action="/players">
        <label>
          <span>Player name</span>
          <input name="query" defaultValue={query} maxLength={80} placeholder="Search players" />
        </label>
        <label>
          <span>Role</span>
          <select name="role" defaultValue={role || ""}>
            <option value="">All roles</option>
            <option value="batter">Batters</option>
            <option value="pitcher">Pitchers</option>
            <option value="two-way">Two-way</option>
          </select>
        </label>
        <label>
          <span>Season</span>
          <input name="season" type="number" min="1876" max="2200" defaultValue={season} />
        </label>
        <button className="button button--primary" type="submit">Apply</button>
      </form>

      {!result.ok ? (
        <Panel className="state-panel" labelledBy="players-error-heading">
          <p className="panel-kicker">Directory unavailable</p>
          <h2 id="players-error-heading">The persisted player index could not be loaded.</h2>
          <p>{result.message} The complete existing player view remains available.</p>
          <LegacyFallback href={legacyUrl} label="Players" />
        </Panel>
      ) : players.length === 0 ? (
        <Panel className="state-panel" labelledBy="players-empty-heading">
          <p className="panel-kicker">No matching players</p>
          <h2 id="players-empty-heading">No persisted profile matches these filters.</h2>
          <p>Try a shorter name, another role, or remove the season filter.</p>
        </Panel>
      ) : (
        <section className="player-grid" aria-label="Player directory results">
          {players.map((player) => (
            <article className="player-card" key={player.player_id}>
              <div>
                <span className="player-monogram" aria-hidden="true">
                  {(player.name || "?").split(" ").map((part) => part[0]).slice(0, 2).join("")}
                </span>
                <div>
                  <p className="panel-kicker">{player.player_type}</p>
                  <h2>{player.name || `Player ${player.player_id}`}</h2>
                </div>
              </div>
              <dl className="player-card-meta">
                <div><dt>Latest season</dt><dd>{player.latest_season || "-"}</dd></div>
                <div><dt>Last game</dt><dd>{player.last_game_date || "-"}</dd></div>
              </dl>
              <footer>
                <Link href={`/players/${player.player_id}${season ? `?season=${season}` : ""}`}>
                  Open profile
                </Link>
                <Link href={`/matchups?batter=${player.player_id}${season ? `&season=${season}` : ""}`}>
                  Use as batter
                </Link>
              </footer>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
