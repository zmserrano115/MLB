import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";

import { ResearchTable } from "../../../components/research-table";
import { getTeamLeaderboard } from "../../../lib/api";
import { safeFilter } from "../../../lib/date-state";
import { safeGroup, safeSeason } from "../../../lib/research-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Team stats" };
type PageProps = { searchParams: Promise<Record<string, string | string[] | undefined>> };

const sortOptions = {
  batting: [["runs", "Runs"], ["home_runs", "Home runs"], ["average", "Average"], ["strikeout_rate", "Lowest strikeout rate"]],
  pitching: [["era", "ERA"], ["strikeouts", "Strikeouts"], ["runs_allowed", "Runs allowed"], ["walks_allowed", "Walks allowed"]],
} as const;
function rate(value: number | null | undefined, digits = 3) { return value == null ? "-" : value.toFixed(digits).replace(/^0/, ""); }
function innings(outs: number) { return `${Math.floor(outs / 3)}.${outs % 3}`; }

export default async function TeamStatsPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const group = safeGroup(query.group);
  const season = safeSeason(query.season);
  const sortCandidate = safeFilter(query.sort, 32);
  const sort = sortOptions[group].some(([key]) => key === sortCandidate) ? sortCandidate : sortOptions[group][0][0];
  const result = await getTeamLeaderboard({ season, group, sort });
  const rows = result.ok ? result.value.data : [];

  return <main id="main-content" className="page-stack research-page">
    <PageHeader eyebrow="Club comparisons" title="Team stats" summary="Compare batting production, pitching prevention, and the run environment from persisted team-season summaries."><StatusPill tone={rows.length ? "healthy" : "warning"}>{rows.length ? `${rows.length} clubs` : "No rows"}</StatusPill></PageHeader>
    <form className="filter-bar" action="/stats/teams">
      <label><span>Group</span><select name="group" defaultValue={group}><option value="batting">Batting</option><option value="pitching">Pitching</option></select></label>
      <label><span>Season</span><input name="season" type="number" min="1876" max="2200" defaultValue={season} /></label>
      <label><span>Sort</span><select name="sort" defaultValue={sort}>{sortOptions[group].map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <button className="button button--primary" type="submit">Compare</button>
    </form>
    {!rows.length ? <Panel className="state-panel" labelledBy="team-stats-empty"><h2 id="team-stats-empty">No team summaries match.</h2><p>{result.ok ? "Try another season." : result.message}</p></Panel>
    : <Panel labelledBy="team-leaders"><div className="panel-heading-row"><div><p className="panel-kicker">{group}</p><h2 id="team-leaders">{rows[0]?.season} team comparison</h2></div><StatusPill>Run environment</StatusPill></div>
      {group === "pitching" ? <ResearchTable caption="Team pitching comparison" headers={["Rank", "Team", "G", "IP", "ERA", "R", "ER", "H", "BB", "SO", "HR"]} rows={rows.map((row, index) => [index + 1, row.abbreviation || row.name, row.games, innings(row.innings_outs), rate(row.era, 2), row.runs_allowed, row.earned_runs_allowed, row.hits_allowed, row.walks_allowed, row.strikeouts_pitched, row.home_runs_allowed])} />
      : <ResearchTable caption="Team batting comparison" headers={["Rank", "Team", "G", "PA", "Runs", "H", "HR", "BB", "SO", "AVG", "R/G"]} rows={rows.map((row, index) => [index + 1, row.abbreviation || row.name, row.games, row.pa, row.runs, row.hits, row.home_runs, row.walks, row.strikeouts, rate(row.average), row.games ? (row.runs / row.games).toFixed(2) : "-"])} />}
    </Panel>}
  </main>;
}
