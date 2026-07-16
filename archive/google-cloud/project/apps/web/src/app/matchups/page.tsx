import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { LegacyFallback } from "../../components/legacy-fallback";
import { ResearchTable } from "../../components/research-table";
import { getBatterPitcherMatchup } from "../../lib/api";
import { safePlayerId, safeSeason } from "../../lib/research-state";
import { buildLegacyUrl, resolveLegacyRoute } from "../../lib/route-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Matchups" };

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function rate(value: number | null | undefined) {
  return value == null ? "-" : value.toFixed(3).replace(/^0/, "");
}

export default async function MatchupsPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const batterId = safePlayerId(query.batter);
  const pitcherId = safePlayerId(query.pitcher);
  const season = safeSeason(query.season);
  const result = batterId && pitcherId
    ? await getBatterPitcherMatchup({ batterId, pitcherId, season })
    : null;
  const matchup = result?.ok ? result.value.data : null;
  const legacyState = {
    ...(batterId ? { batter: batterId } : {}),
    ...(pitcherId ? { pitcher: pitcherId } : {}),
    ...(season ? { season: String(season) } : {}),
    type: "batter-vs-pitcher",
  };
  const legacyUrl = buildLegacyUrl(
    process.env.LEGACY_BASE_URL || "http://localhost:8501/",
    resolveLegacyRoute(["matchups"])!,
    legacyState,
  );

  return (
    <main id="main-content" className="page-stack research-page">
      <PageHeader
        eyebrow="Head-to-head research"
        title="Matchups"
        summary="Compare a batter and pitcher using persisted direct history, with the selected season and players preserved in the URL."
      >
        <StatusPill tone={result?.ok && result.value.meta.stale ? "warning" : "healthy"}>
          {result?.ok && result.value.meta.stale ? "Stale snapshot" : "Persisted history"}
        </StatusPill>
        <LegacyFallback href={legacyUrl} label="complete Matchups" />
      </PageHeader>

      <nav className="segment-nav" aria-label="Matchup research">
        <Link aria-current="page" href="/matchups">Batter vs pitcher</Link>
        <Link href="/matchups/pitcher-vs-opponent">Pitcher vs opponent</Link>
        <Link href="/matchups/bullpen">Projected bullpen</Link>
      </nav>

      <form className="filter-bar research-filter" action="/matchups">
        <label>
          <span>Batter MLB ID</span>
          <input name="batter" inputMode="numeric" pattern="[0-9]+" maxLength={20} defaultValue={batterId} placeholder="e.g. 592450" />
        </label>
        <label>
          <span>Pitcher MLB ID</span>
          <input name="pitcher" inputMode="numeric" pattern="[0-9]+" maxLength={20} defaultValue={pitcherId} placeholder="e.g. 543037" />
        </label>
        <label>
          <span>Season</span>
          <input name="season" type="number" min="1876" max="2200" defaultValue={season} />
        </label>
        <button className="button button--primary" type="submit">Compare</button>
      </form>

      <div className="research-helper">
        <span>Need a player ID?</span>
        <Link href="/players">Search the player directory</Link>
        <Link href={`/research/batter-vs-pitcher?${new URLSearchParams(legacyState)}`}>
          Open Advanced HVP handoff
        </Link>
      </div>

      {!batterId || !pitcherId ? (
        <Panel className="state-panel" labelledBy="matchup-start-heading">
          <p className="panel-kicker">Choose two players</p>
          <h2 id="matchup-start-heading">Enter a batter and pitcher to load direct history.</h2>
          <p>
            Player IDs come from the persisted directory. This page does not call an upstream
            baseball provider during the request.
          </p>
        </Panel>
      ) : !matchup ? (
        <Panel className="state-panel" labelledBy="matchup-empty-heading">
          <p className="panel-kicker">No persisted matchup</p>
          <h2 id="matchup-empty-heading">No direct history matches this selection.</h2>
          <p>
            {result && !result.ok ? result.message : "The matchup contains no published plate appearances."}
            {" "}Try removing the season or use the complete legacy research view.
          </p>
          <LegacyFallback href={legacyUrl} label="Matchups" />
        </Panel>
      ) : (
        <>
          <Panel className="matchup-hero" labelledBy="matchup-heading">
            <div className="matchup-names">
              <div>
                <span>Batter</span>
                <h2 id="matchup-heading">{matchup.batter_name || matchup.batter_id}</h2>
                <Link href={`/players/${matchup.batter_id}`}>Open profile</Link>
              </div>
              <strong aria-hidden="true">VS</strong>
              <div>
                <span>Pitcher</span>
                <h2>{matchup.pitcher_name || matchup.pitcher_id}</h2>
                <Link href={`/players/${matchup.pitcher_id}?group=pitching`}>Open profile</Link>
              </div>
            </div>
            <dl className="metric-grid metric-grid--wide">
              <div><dt>PA</dt><dd>{matchup.pa}</dd></div>
              <div><dt>AVG</dt><dd>{rate(matchup.batting_average)}</dd></div>
              <div><dt>OBP</dt><dd>{rate(matchup.on_base_percentage)}</dd></div>
              <div><dt>SLG</dt><dd>{rate(matchup.slugging_percentage)}</dd></div>
              <div><dt>H</dt><dd>{matchup.hits}</dd></div>
              <div><dt>HR</dt><dd>{matchup.home_runs}</dd></div>
              <div><dt>BB</dt><dd>{matchup.walks}</dd></div>
              <div><dt>SO</dt><dd>{matchup.strikeouts}</dd></div>
            </dl>
          </Panel>

          <Panel labelledBy="matchup-log-heading">
            <div className="panel-heading-row">
              <div>
                <p className="panel-kicker">Direct history</p>
                <h2 id="matchup-log-heading">Game-by-game results</h2>
              </div>
              <StatusPill>{matchup.games} games</StatusPill>
            </div>
            <ResearchTable
              caption={`${matchup.batter_name || "Batter"} versus ${matchup.pitcher_name || "pitcher"}`}
              headers={["Date", "Opponent", "PA", "AB", "H", "BB", "SO", "HR", "RBI", "TB"]}
              rows={matchup.game_logs.map((log) => [
                log.game_date,
                log.opponent || "-",
                log.pa ?? "-",
                log.ab ?? "-",
                log.hits ?? "-",
                log.walks ?? "-",
                log.strikeouts ?? "-",
                log.home_runs ?? "-",
                log.rbi ?? "-",
                log.total_bases ?? "-",
              ])}
            />
          </Panel>
        </>
      )}
    </main>
  );
}
