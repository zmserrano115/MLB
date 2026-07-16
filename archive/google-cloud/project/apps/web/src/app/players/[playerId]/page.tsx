import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { LegacyFallback } from "../../../components/legacy-fallback";
import { ResearchTable } from "../../../components/research-table";
import { getPlayerProfile } from "../../../lib/api";
import { safeGroup, safePlayerId, safeSeason } from "../../../lib/research-state";
import { buildLegacyUrl, resolveLegacyRoute } from "../../../lib/route-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Player profile" };

type PageProps = {
  params: Promise<{ playerId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function innings(outs: number | null | undefined) {
  if (outs == null) return "-";
  return `${Math.floor(outs / 3)}.${outs % 3}`;
}

function rate(value: number | null | undefined) {
  return value == null ? "-" : value.toFixed(3).replace(/^0/, "");
}

export default async function PlayerProfilePage({ params, searchParams }: PageProps) {
  const route = await params;
  const query = await searchParams;
  const playerId = safePlayerId(route.playerId);
  const season = safeSeason(query.season);
  const group = safeGroup(query.group);
  const result = playerId
    ? await getPlayerProfile(playerId, { season, group })
    : { ok: false as const, status: 422, message: "The player identifier is invalid." };
  const profile = result.ok ? result.value.data : null;
  const legacyUrl = buildLegacyUrl(
    process.env.LEGACY_BASE_URL || "http://localhost:8501/",
    resolveLegacyRoute(["players", playerId || "invalid"])!,
    {
      player_id: playerId,
      ...(season ? { season: String(season) } : {}),
      group,
    },
  );
  const stateQuery = `${season ? `season=${season}&` : ""}group=`;

  return (
    <main id="main-content" className="page-stack research-page">
      <PageHeader
        eyebrow="Player profile"
        title={profile?.player.name || "Player unavailable"}
        summary={profile
          ? `${profile.player.player_type} - latest persisted activity ${profile.player.last_game_date || "not recorded"}.`
          : "The requested persisted player profile could not be loaded."}
      >
        {profile ? (
          <StatusPill tone={result.ok && result.value.meta.stale ? "warning" : "healthy"}>
            {result.ok && result.value.meta.stale ? "Stale snapshot" : "Persisted profile"}
          </StatusPill>
        ) : null}
        <LegacyFallback href={legacyUrl} label="complete player profile" />
      </PageHeader>

      {!profile ? (
        <Panel className="state-panel" labelledBy="profile-error-heading">
          <p className="panel-kicker">Profile unavailable</p>
          <h2 id="profile-error-heading">This player is not in the persisted profile index.</h2>
          <p>{result.ok ? "No player record was returned." : result.message}</p>
          <Link className="button button--primary" href="/players">Back to players</Link>
        </Panel>
      ) : (
        <>
          <nav className="segment-nav" aria-label="Player log group">
            <Link aria-current={group === "batting" ? "page" : undefined} href={`?${stateQuery}batting`}>
              Batting logs
            </Link>
            <Link aria-current={group === "pitching" ? "page" : undefined} href={`?${stateQuery}pitching`}>
              Pitching logs
            </Link>
            <Link href={`/matchups?batter=${playerId}${season ? `&season=${season}` : ""}`}>
              Build matchup
            </Link>
          </nav>

          <section className="summary-grid" aria-label="Player season summaries">
            <Panel labelledBy="batting-summary-heading">
              <div className="panel-heading-row">
                <div>
                  <p className="panel-kicker">Batting</p>
                  <h2 id="batting-summary-heading">{profile.batting?.season || season || "Latest"} summary</h2>
                </div>
                <StatusPill>{profile.batting ? `${profile.batting.games} games` : "No data"}</StatusPill>
              </div>
              {profile.batting ? (
                <dl className="metric-grid">
                  <div><dt>AVG</dt><dd>{rate(profile.batting.batting_average)}</dd></div>
                  <div><dt>OBP</dt><dd>{rate(profile.batting.on_base_percentage)}</dd></div>
                  <div><dt>SLG</dt><dd>{rate(profile.batting.slugging_percentage)}</dd></div>
                  <div><dt>HR</dt><dd>{profile.batting.home_runs}</dd></div>
                  <div><dt>RBI</dt><dd>{profile.batting.rbi}</dd></div>
                  <div><dt>SO</dt><dd>{profile.batting.strikeouts}</dd></div>
                </dl>
              ) : <p>No batting summary is published for this selection.</p>}
            </Panel>

            <Panel labelledBy="pitching-summary-heading">
              <div className="panel-heading-row">
                <div>
                  <p className="panel-kicker">Pitching</p>
                  <h2 id="pitching-summary-heading">{profile.pitching?.season || season || "Latest"} summary</h2>
                </div>
                <StatusPill>{profile.pitching ? `${profile.pitching.games} games` : "No data"}</StatusPill>
              </div>
              {profile.pitching ? (
                <dl className="metric-grid">
                  <div><dt>ERA</dt><dd>{profile.pitching.earned_run_average?.toFixed(2) || "-"}</dd></div>
                  <div><dt>WHIP</dt><dd>{profile.pitching.whip?.toFixed(2) || "-"}</dd></div>
                  <div><dt>IP</dt><dd>{innings(profile.pitching.innings_outs)}</dd></div>
                  <div><dt>Starts</dt><dd>{profile.pitching.starts}</dd></div>
                  <div><dt>SO</dt><dd>{profile.pitching.strikeouts}</dd></div>
                  <div><dt>HR</dt><dd>{profile.pitching.home_runs}</dd></div>
                </dl>
              ) : <p>No pitching summary is published for this selection.</p>}
            </Panel>
          </section>

          <Panel labelledBy="game-log-heading">
            <div className="panel-heading-row">
              <div>
                <p className="panel-kicker">Recent form</p>
                <h2 id="game-log-heading">{group === "pitching" ? "Pitching" : "Batting"} game logs</h2>
              </div>
              <StatusPill>{profile.game_logs.length} rows</StatusPill>
            </div>
            {profile.game_logs.length ? (
              <ResearchTable
                caption={`${profile.player.name || "Player"} ${group} game logs`}
                headers={group === "pitching"
                  ? ["Date", "Opponent", "IP", "Pitches", "BF", "H", "BB", "SO", "HR", "ER"]
                  : ["Date", "Opponent", "PA", "AB", "H", "BB", "SO", "HR", "RBI", "TB"]}
                rows={profile.game_logs.map((log) => group === "pitching"
                  ? [log.game_date, log.opponent || "-", innings(log.innings_outs), log.pitch_count ?? "-", log.batters_faced ?? "-", log.hits ?? "-", log.walks ?? "-", log.strikeouts ?? "-", log.home_runs ?? "-", log.earned_runs ?? "-"]
                  : [log.game_date, log.opponent || "-", log.pa ?? "-", log.ab ?? "-", log.hits ?? "-", log.walks ?? "-", log.strikeouts ?? "-", log.home_runs ?? "-", log.rbi ?? "-", log.total_bases ?? "-"])}
              />
            ) : <p>No recent {group} logs match this season.</p>}
          </Panel>
        </>
      )}
    </main>
  );
}
