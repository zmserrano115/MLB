import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { ResearchTable } from "../../../components/research-table";
import { getBullpenProjection } from "../../../lib/api";
import { safeFilter } from "../../../lib/date-state";
import { safePlayerId } from "../../../lib/research-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Projected bullpen" };
type PageProps = { searchParams: Promise<Record<string, string | string[] | undefined>> };

function percent(value: number | null | undefined) { return value == null ? "-" : `${(value * 100).toFixed(0)}%`; }

export default async function BullpenPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const gameId = safeFilter(query.game, 80);
  const team = safeFilter(query.team, 16).toUpperCase();
  const batterId = safePlayerId(query.batter);
  const result = gameId ? await getBullpenProjection({ gameId, team: team || undefined, batterId: batterId || undefined }) : null;
  const rows = result?.ok ? result.value.data : [];

  return <main id="main-content" className="page-stack research-page">
    <PageHeader eyebrow="Precomputed relief paths" title="Projected bullpen" summary="Review availability, recent workload, appearance probability, expected batters faced, and persisted batter fit."><StatusPill tone={rows.length ? "healthy" : "warning"}>{rows.length ? `${rows.length} relievers` : "Select a game"}</StatusPill></PageHeader>
    <nav className="segment-nav" aria-label="Matchup research"><Link href="/matchups">Batter vs pitcher</Link><Link href="/matchups/pitcher-vs-opponent">Pitcher vs opponent</Link><Link aria-current="page" href="/matchups/bullpen">Projected bullpen</Link></nav>
    <form className="filter-bar" action="/matchups/bullpen">
      <label><span>Canonical game ID</span><input name="game" defaultValue={gameId} maxLength={80} placeholder="mlb:746123" required /></label>
      <label><span>Pitching team</span><input name="team" defaultValue={team} maxLength={16} placeholder="NYY" /></label>
      <label><span>Batter MLB ID</span><input name="batter" inputMode="numeric" pattern="[0-9]+" defaultValue={batterId} /></label>
      <button className="button button--primary" type="submit">Load path</button>
    </form>
    {!gameId ? <Panel className="state-panel" labelledBy="bullpen-start"><h2 id="bullpen-start">Choose a game.</h2><p>Open a game from the schedule and use its canonical ID. Batter fit is optional.</p></Panel>
    : !rows.length ? <Panel className="state-panel" labelledBy="bullpen-empty"><h2 id="bullpen-empty">No active projection is published.</h2><p>{result && !result.ok ? result.message : "The worker has not published a relief path for this game and team."}</p></Panel>
    : <Panel labelledBy="bullpen-table"><div className="panel-heading-row"><div><p className="panel-kicker">Likely relief path</p><h2 id="bullpen-table">Availability and batter fit</h2></div><StatusPill>{rows[0]?.generation}</StatusPill></div>
      <ResearchTable caption="Projected bullpen" headers={["Pitcher", "Role", "Availability", "Score", "Appearance", "Expected BF", "Workload", "Batter history", "Reason"]} rows={rows.map((row) => [row.pitcher_name || row.pitcher_id, row.projected_role || "-", row.availability_label || "-", row.availability_score?.toFixed(2) || "-", percent(row.appearance_probability), row.expected_batters_faced_min == null ? "-" : `${row.expected_batters_faced_min}-${row.expected_batters_faced_max ?? row.expected_batters_faced_min}`, row.recent_workload || "-", row.batter_pa == null ? "-" : `${row.batter_hits ?? 0}-${row.batter_pa}, ${row.batter_strikeouts ?? 0} K`, row.reason || "-"])} />
    </Panel>}
  </main>;
}
