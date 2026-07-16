import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { ResearchTable } from "../../../components/research-table";
import { getPitcherOpponent } from "../../../lib/api";
import { safePlayerId, safeSeason } from "../../../lib/research-state";
import { safeFilter } from "../../../lib/date-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Pitcher vs opponent" };
type PageProps = { searchParams: Promise<Record<string, string | string[] | undefined>> };

function innings(outs: number) { return `${Math.floor(outs / 3)}.${outs % 3}`; }

export default async function PitcherOpponentPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const pitcherId = safePlayerId(query.pitcher);
  const team = safeFilter(query.team, 80).toUpperCase();
  const season = safeSeason(query.season);
  const result = pitcherId ? await getPitcherOpponent({ pitcherId, team: team || undefined, season }) : null;
  const data = result?.ok ? result.value.data : null;

  return <main id="main-content" className="page-stack research-page">
    <PageHeader eyebrow="Pitching matchup research" title="Pitcher vs opponent" summary="Compare a pitcher's persisted history against clubs, including workload and strikeout production by game."><StatusPill>Historical facts</StatusPill></PageHeader>
    <nav className="segment-nav" aria-label="Matchup research"><Link href="/matchups">Batter vs pitcher</Link><Link aria-current="page" href="/matchups/pitcher-vs-opponent">Pitcher vs opponent</Link><Link href="/matchups/bullpen">Projected bullpen</Link></nav>
    <form className="filter-bar" action="/matchups/pitcher-vs-opponent">
      <label><span>Pitcher MLB ID</span><input name="pitcher" inputMode="numeric" pattern="[0-9]+" defaultValue={pitcherId} required /></label>
      <label><span>Opponent</span><input name="team" defaultValue={team} maxLength={80} placeholder="NYY or New York Yankees" /></label>
      <label><span>Season</span><input name="season" type="number" min="1876" max="2200" defaultValue={season} /></label>
      <button className="button button--primary" type="submit">Compare</button>
    </form>
    {!pitcherId ? <Panel className="state-panel" labelledBy="pitcher-start"><h2 id="pitcher-start">Choose a pitcher.</h2><p>Use the player directory to find an MLB player ID, then optionally narrow to one opponent or season.</p></Panel>
    : !data?.game_logs.length ? <Panel className="state-panel" labelledBy="pitcher-empty"><h2 id="pitcher-empty">No matching pitching history.</h2><p>{result && !result.ok ? result.message : "Try removing the opponent or season filter."}</p></Panel>
    : <>
      <Panel labelledBy="opponent-splits"><div className="panel-heading-row"><div><p className="panel-kicker">Opponent splits</p><h2 id="opponent-splits">Workload and strikeout profile</h2></div><StatusPill>{data.game_logs.length} recent games</StatusPill></div>
        <ResearchTable caption="Pitcher opponent splits" headers={["Opponent", "Games", "IP", "BF", "SO", "K%", "BB", "H", "HR", "ER"]} rows={data.splits.map((row) => [row.opponent || "All", row.games, innings(row.innings_outs), row.batters_faced, row.strikeouts, row.batters_faced ? `${(100 * row.strikeouts / row.batters_faced).toFixed(1)}%` : "-", row.walks, row.hits, row.home_runs, row.earned_runs])} />
      </Panel>
      <Panel labelledBy="strikeout-log"><div className="panel-heading-row"><div><p className="panel-kicker">Strikeout outcomes</p><h2 id="strikeout-log">Game log</h2></div></div>
        <ResearchTable caption="Pitcher game history" headers={["Date", "Opponent", "Role", "IP", "Pitches", "BF", "SO", "BB", "H", "HR", "ER"]} rows={data.game_logs.map((row) => [row.game_date, row.opponent || "-", row.is_starter ? "Starter" : "Relief", innings(row.innings_outs), row.pitch_count ?? "-", row.batters_faced, row.strikeouts, row.walks, row.hits, row.home_runs, row.earned_runs])} />
      </Panel>
    </>}
  </main>;
}
