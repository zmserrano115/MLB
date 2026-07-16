import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { ResearchTable } from "../../../components/research-table";
import { getPlayerLeaderboard } from "../../../lib/api";
import { safeFilter } from "../../../lib/date-state";
import { safeGroup, safeSeason } from "../../../lib/research-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Player stats" };
type PageProps = { searchParams: Promise<Record<string, string | string[] | undefined>> };

const sortOptions = {
  batting: [["home_runs", "Home runs"], ["hits", "Hits"], ["rbi", "RBI"], ["average", "Average"], ["ops", "OPS"]],
  pitching: [["strikeouts", "Strikeouts"], ["era", "ERA"], ["whip", "WHIP"], ["innings", "Innings"]],
} as const;
function rate(value: number | null | undefined, digits = 3) { return value == null ? "-" : value.toFixed(digits).replace(/^0/, ""); }
function innings(outs: number | null | undefined) { return outs == null ? "-" : `${Math.floor(outs / 3)}.${outs % 3}`; }

export default async function PlayerStatsPage({ searchParams }: PageProps) {
  const queryParams = await searchParams;
  const group = safeGroup(queryParams.group);
  const season = safeSeason(queryParams.season);
  const query = safeFilter(queryParams.query, 80);
  const sortCandidate = safeFilter(queryParams.sort, 32);
  const sort = sortOptions[group].some(([key]) => key === sortCandidate) ? sortCandidate : sortOptions[group][0][0];
  const result = await getPlayerLeaderboard({ season, group, sort, query: query || undefined });
  const rows = result.ok ? result.value.data : [];

  return <main id="main-content" className="page-stack research-page">
    <PageHeader eyebrow="Season leaderboards" title="Player stats" summary="Sort and filter persisted batting and pitching summaries, then move directly into a player profile."><StatusPill tone={rows.length ? "healthy" : "warning"}>{rows.length ? `${rows.length} players` : "No rows"}</StatusPill></PageHeader>
    <form className="filter-bar" action="/stats/players">
      <label><span>Group</span><select name="group" defaultValue={group}><option value="batting">Batting</option><option value="pitching">Pitching</option></select></label>
      <label><span>Season</span><input name="season" type="number" min="1876" max="2200" defaultValue={season} /></label>
      <label><span>Sort</span><select name="sort" defaultValue={sort}>{sortOptions[group].map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label><span>Player</span><input name="query" defaultValue={query} maxLength={80} placeholder="Search name" /></label>
      <button className="button button--primary" type="submit">Apply</button>
    </form>
    {!rows.length ? <Panel className="state-panel" labelledBy="player-stats-empty"><h2 id="player-stats-empty">No leaderboard rows match.</h2><p>{result.ok ? "Try another season or clear the player filter." : result.message}</p></Panel>
    : <Panel labelledBy="player-leaders"><div className="panel-heading-row"><div><p className="panel-kicker">{group}</p><h2 id="player-leaders">{rows[0]?.season} leaders</h2></div><StatusPill>Persisted summary</StatusPill></div>
      {group === "pitching" ? <ResearchTable caption="Pitching leaders" headers={["Rank", "Pitcher", "G", "GS", "IP", "SO", "ERA", "WHIP", "BB", "HR"]} rows={rows.map((row, index) => [index + 1, <Link key={row.player_id} href={`/players/${row.player_id}?group=pitching&season=${row.season}`}>{row.name || row.player_id}</Link>, row.games, row.starts ?? "-", innings(row.innings_outs), row.strikeouts, rate(row.era, 2), rate(row.whip, 2), row.walks, row.home_runs ?? "-"])} />
      : <ResearchTable caption="Batting leaders" headers={["Rank", "Batter", "Team", "G", "PA", "H", "HR", "RBI", "AVG", "OPS", "SO"]} rows={rows.map((row, index) => [index + 1, <Link key={row.player_id} href={`/players/${row.player_id}?season=${row.season}`}>{row.name || row.player_id}</Link>, row.team || "-", row.games, row.pa ?? "-", row.hits ?? "-", row.home_runs ?? "-", row.rbi ?? "-", rate(row.average), rate(row.ops), row.strikeouts])} />}
    </Panel>}
  </main>;
}
