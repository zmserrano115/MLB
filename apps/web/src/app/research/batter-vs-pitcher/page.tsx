import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { ResearchTable } from "../../../components/research-table";
import { getAdvancedMatchup, getBatterPitcherMatchup } from "../../../lib/api";
import { safePlayerId, safeSeason } from "../../../lib/research-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Advanced HVP" };

type PageProps = { searchParams: Promise<Record<string, string | string[] | undefined>> };

function value(number: number | null | undefined, digits = 1) {
  return number == null ? "-" : number.toFixed(digits);
}

export default async function AdvancedHvpPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const batterId = safePlayerId(query.batter);
  const pitcherId = safePlayerId(query.pitcher);
  const season = safeSeason(query.season);
  const [advancedResult, historyResult] = batterId && pitcherId
    ? await Promise.all([
        getAdvancedMatchup({ batterId, pitcherId, season }),
        getBatterPitcherMatchup({ batterId, pitcherId, season }),
      ])
    : [null, null];
  const advanced = advancedResult?.ok ? advancedResult.value.data : null;
  const history = historyResult?.ok ? historyResult.value.data : null;

  return (
    <main id="main-content" className="page-stack research-page">
      <PageHeader
        eyebrow="Persisted pitch research"
        title="Advanced HVP"
        summary="Inspect direct history, pitch mix, plate-appearance sequences, and contact quality without provider calls in the request path."
      >
        <StatusPill tone={advanced?.coverage.pitch_count ? "healthy" : "warning"}>
          {advanced?.coverage.pitch_count ? `${advanced.coverage.pitch_count} pitches` : "Coverage explicit"}
        </StatusPill>
      </PageHeader>

      <form className="filter-bar research-filter" action="/research/batter-vs-pitcher">
        <label><span>Batter MLB ID</span><input name="batter" inputMode="numeric" pattern="[0-9]+" defaultValue={batterId} required /></label>
        <label><span>Pitcher MLB ID</span><input name="pitcher" inputMode="numeric" pattern="[0-9]+" defaultValue={pitcherId} required /></label>
        <label><span>Season</span><input name="season" type="number" min="1876" max="2200" defaultValue={season} /></label>
        <button className="button button--primary" type="submit">Research</button>
      </form>
      <div className="research-helper"><Link href="/players">Find player IDs</Link><Link href={`/matchups?batter=${batterId}&pitcher=${pitcherId}`}>Open direct matchup</Link></div>

      {!batterId || !pitcherId ? (
        <Panel className="state-panel" labelledBy="advanced-start"><h2 id="advanced-start">Choose a batter and pitcher.</h2><p>The URL preserves both player IDs and the optional season.</p></Panel>
      ) : (
        <>
          <Panel labelledBy="direct-history-heading">
            <div className="panel-heading-row"><div><p className="panel-kicker">Direct history</p><h2 id="direct-history-heading">Outcome summary</h2></div><StatusPill>{history ? `${history.pa} PA` : "No history"}</StatusPill></div>
            {history ? <dl className="metric-grid metric-grid--wide">
              <div><dt>Games</dt><dd>{history.games}</dd></div><div><dt>PA</dt><dd>{history.pa}</dd></div>
              <div><dt>H</dt><dd>{history.hits}</dd></div><div><dt>HR</dt><dd>{history.home_runs}</dd></div>
              <div><dt>SO</dt><dd>{history.strikeouts}</dd></div><div><dt>BB</dt><dd>{history.walks}</dd></div>
              <div><dt>AVG</dt><dd>{value(history.batting_average, 3)}</dd></div><div><dt>SLG</dt><dd>{value(history.slugging_percentage, 3)}</dd></div>
            </dl> : <p>No persisted direct plate appearances match this selection.</p>}
          </Panel>

          {!advanced?.coverage.pitch_count ? (
            <Panel className="state-panel" labelledBy="pitch-coverage-heading">
              <p className="panel-kicker">Pitch-level coverage</p><h2 id="pitch-coverage-heading">No authoritative pitch events are published for this matchup.</h2>
              <p>Direct history remains available above. Pitch mix, location, sequence, and contact-quality panels stay empty until the Statcast publisher writes the normalized read models.</p>
            </Panel>
          ) : (
            <>
              <Panel labelledBy="pitch-mix-heading"><div className="panel-heading-row"><div><p className="panel-kicker">Pitch mix</p><h2 id="pitch-mix-heading">Results by pitch type</h2></div><StatusPill>{advanced.coverage.games} games</StatusPill></div>
                <ResearchTable caption="Pitch type matchup results" headers={["Pitch", "Count", "Velocity", "Whiff", "Hard hit", "Barrel", "xwOBA"]} rows={advanced.pitch_types.map((row) => [row.pitch_name || row.pitch_type, row.pitch_count, value(row.average_velocity), value(row.whiff_percentage, 3), value(row.hard_hit_percentage, 3), value(row.barrel_percentage, 3), value(row.expected_woba, 3)])} />
              </Panel>
              <Panel labelledBy="sequence-heading"><div className="panel-heading-row"><div><p className="panel-kicker">Approach</p><h2 id="sequence-heading">Plate-appearance sequences and contact</h2></div></div>
                <ResearchTable caption="Plate appearance sequences" headers={["Date", "Result", "Sequence", "Pitches", "Exit velo", "Launch angle", "Distance", "Quality"]} rows={advanced.sequences.map((row) => [row.game_date, row.result || "-", row.pitch_sequence, row.pitch_count, value(row.launch_speed), value(row.launch_angle), value(row.estimated_distance, 0), row.barrel ? "Barrel" : row.hard_hit ? "Hard hit" : "-"])} />
              </Panel>
            </>
          )}
        </>
      )}
    </main>
  );
}
