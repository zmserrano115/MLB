import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { ResearchTable } from "../../components/research-table";
import { getStreaks } from "../../lib/api";
import { safeFilter } from "../../lib/date-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Streaks" };
type PageProps = { searchParams: Promise<Record<string, string | string[] | undefined>> };

const metrics = {
  batter: [["hit", "Hit"], ["home_run", "Home run"], ["two_total_bases", "2+ total bases"], ["rbi", "RBI"]],
  pitcher: [["five_strikeouts", "5+ strikeouts"], ["seven_strikeouts", "7+ strikeouts"], ["scoreless", "Scoreless"]],
  team: [["wins", "Wins"]],
} as const;

export default async function StreaksPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const groupCandidate = safeFilter(query.group, 16);
  const group = groupCandidate === "pitcher" || groupCandidate === "team" ? groupCandidate : "batter";
  const metricCandidate = safeFilter(query.metric, 48);
  const metric = metrics[group].some(([key]) => key === metricCandidate) ? metricCandidate : metrics[group][0][0];
  const dateCandidate = safeFilter(query.date, 10);
  const date = /^\d{4}-\d{2}-\d{2}$/.test(dateCandidate) ? dateCandidate : "";
  const result = await getStreaks({ date: date || undefined, group, metric });
  const rows = result.ok ? result.value.data : [];

  return <main id="main-content" className="page-stack research-page">
    <PageHeader eyebrow="Precomputed current runs" title="Streaks" summary="Rank active batter, pitcher, and team streaks from persisted completed-game facts."><StatusPill tone={rows.length ? "healthy" : "warning"}>{rows.length ? `${rows.length} active` : "No active runs"}</StatusPill></PageHeader>
    <form className="filter-bar" action="/streaks">
      <label><span>Group</span><select name="group" defaultValue={group}><option value="batter">Batters</option><option value="pitcher">Pitchers</option><option value="team">Teams</option></select></label>
      <label><span>Metric</span><select name="metric" defaultValue={metric}>{metrics[group].map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label><span>Through date</span><input name="date" type="date" defaultValue={date} /></label>
      <button className="button button--primary" type="submit">Update</button>
    </form>
    <div className="segment-nav" aria-label="Streak groups">{(["batter", "pitcher", "team"] as const).map((item) => <Link key={item} aria-current={item === group ? "page" : undefined} href={`/streaks?group=${item}&metric=${metrics[item][0][0]}`}>{item === "team" ? "Team wins" : `${item[0].toUpperCase()}${item.slice(1)}s`}</Link>)}</div>
    {!rows.length ? <Panel className="state-panel" labelledBy="streak-empty"><h2 id="streak-empty">No published streaks match this view.</h2><p>{result.ok ? "Choose another metric or remove the historical date." : result.message}</p></Panel>
    : <Panel labelledBy="streak-leaders"><div className="panel-heading-row"><div><p className="panel-kicker">Active leaderboard</p><h2 id="streak-leaders">Consecutive qualifying games</h2></div><StatusPill>{rows[0]?.through_date}</StatusPill></div>
      <ResearchTable caption={`${group} ${metric} streak leaders`} headers={["Rank", "Player / team", "Team", "Streak", "Last game"]} rows={rows.map((row, index) => [index + 1, row.subject_name || row.subject_id || "Unknown", row.team || "-", `${row.streak} games`, row.last_game_date || "-"])} />
    </Panel>}
  </main>;
}
