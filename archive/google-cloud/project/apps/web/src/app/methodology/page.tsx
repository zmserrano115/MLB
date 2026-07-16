import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Methodology" };

const principles = [
  ["Facts before summaries", "Historical facts are stored once, then summaries are rebuilt from those facts so a correction has one traceable path."],
  ["Context is explicit", "Opponent, handedness, park, weather, role, workload, and sample size remain visible instead of disappearing behind a single grade."],
  ["Freshness is a feature", "Every provider has a durable watermark. Stale or degraded data is labeled; a temporary provider failure never becomes invented certainty."],
  ["One calculation", "Python domain functions remain the source of truth. The web interface presents API results and does not recreate scoring logic in TypeScript."],
] as const;

export default function MethodologyPage() {
  return (
    <main id="main-content" className="page-stack methodology-page">
      <PageHeader
        eyebrow="How All Rise works"
        title="Evidence in. Context around it. Judgment stays yours."
        summary="The product combines official and historical baseball data into transparent research views. It highlights signal and uncertainty without presenting a model output as a guarantee."
      >
        <StatusPill tone="healthy">Migrated page</StatusPill>
      </PageHeader>

      <section className="principle-grid" aria-label="Methodology principles">
        {principles.map(([title, copy], index) => (
          <Panel key={title}>
            <span className="principle-number" aria-hidden="true">0{index + 1}</span>
            <h2>{title}</h2>
            <p>{copy}</p>
          </Panel>
        ))}
      </section>

      <Panel labelledBy="pipeline-heading">
        <p className="panel-kicker">Data path</p>
        <h2 id="pipeline-heading">From provider observation to a research view</h2>
        <ol className="process-list">
          <li><strong>Capture.</strong><span>Raw source artifacts are stored immutably with version, size, and checksum.</span></li>
          <li><strong>Normalize.</strong><span>Identifiers, dates, teams, games, players, and events move into constrained PostgreSQL records.</span></li>
          <li><strong>Validate.</strong><span>Duplicate identities, missing fields, ranges, row counts, and partial failures block publication.</span></li>
          <li><strong>Derive.</strong><span>Matchup, pitcher, bullpen, weather, and streak summaries use shared tested domain calculations.</span></li>
          <li><strong>Serve.</strong><span>The API returns versioned responses; Redis improves speed but PostgreSQL remains the authority.</span></li>
        </ol>
      </Panel>

      <Panel labelledBy="interpret-heading">
        <div className="panel-heading-row">
          <div>
            <p className="panel-kicker">Responsible interpretation</p>
            <h2 id="interpret-heading">Read every edge with its limits</h2>
          </div>
        </div>
        <div className="interpret-grid">
          <div><h3>Small samples</h3><p>Direct batter-pitcher history can be useful context, but a handful of plate appearances is not a stable forecast.</p></div>
          <div><h3>Changing roles</h3><p>Lineups, bullpen availability, injuries, openers, and late scratches can change the matchup after a view is generated.</p></div>
          <div><h3>Official corrections</h3><p>Statcast and scoring records can change after a game. Rolling correction windows deliberately replace older observations.</p></div>
          <div><h3>Weather uncertainty</h3><p>Forecasts are directional and roof status matters. Weather adjustments are shown as context, not certainty.</p></div>
        </div>
      </Panel>

      <Panel className="migration-panel" labelledBy="migration-heading">
        <div>
          <p className="panel-kicker">Safe migration</p>
          <h2 id="migration-heading">Pages move only after parity</h2>
          <p>
            The Next.js interface is replacing the existing application one route at a time.
            Until a route passes data, URL, accessibility, mobile, and failure-state checks, its
            navigation link opens a context-preserving legacy handoff. No working feature is
            deleted to make the migration look complete.
          </p>
        </div>
        <StatusPill tone="warning">Strangler migration</StatusPill>
      </Panel>
    </main>
  );
}
