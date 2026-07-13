import type { Readiness } from "@all-rise/shared-types";
import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import Link from "next/link";

import { getDataStatus, getReadiness } from "../lib/api";

export const dynamic = "force-dynamic";

function readinessTone(readiness: Readiness | null) {
  if (!readiness) return "danger" as const;
  if (readiness.cache_status !== "ready") return "warning" as const;
  return "healthy" as const;
}

function sourceTone(status: string) {
  if (["fresh", "ready", "snapshot"].includes(status.toLowerCase())) return "healthy" as const;
  if (["degraded", "stale"].includes(status.toLowerCase())) return "warning" as const;
  return "neutral" as const;
}

export default async function Home() {
  const [readinessResult, sourcesResult] = await Promise.all([
    getReadiness(),
    getDataStatus(),
  ]);
  const readiness = readinessResult.ok ? readinessResult.value.data : null;
  const sources = sourcesResult.ok ? sourcesResult.value.data : [];

  return (
    <main id="main-content" className="page-stack">
      <PageHeader
        eyebrow="Command center"
        title="Baseball intelligence, without the guesswork."
        summary="All Rise brings schedules, matchup history, weather context, and live analysis into one consistent decision surface."
      >
        <Link className="button button--primary" href="/games">
          Open today&apos;s games
        </Link>
      </PageHeader>

      <section className="hero-grid" aria-label="Application overview">
        <Panel className="hero-card hero-card--primary">
          <div>
            <p className="panel-kicker">Today at a glance</p>
            <h2>One route to every angle.</h2>
            <p>
              Start with the slate, move into hitter-pitcher research, then keep the same
              game and player context as you explore deeper.
            </p>
          </div>
          <div className="hero-route-list" aria-label="Primary research routes">
            <Link href="/games">Games</Link>
            <Link href="/matchups">Matchups</Link>
            <Link href="/research/batter-vs-pitcher">Advanced HVP</Link>
            <Link href="/streaks">Streaks</Link>
          </div>
        </Panel>

        <Panel className="system-card" labelledBy="system-health-heading">
          <div className="panel-heading-row">
            <div>
              <p className="panel-kicker">Platform status</p>
              <h2 id="system-health-heading">Data systems</h2>
            </div>
            <StatusPill tone={readinessTone(readiness)}>
              {readiness ? "Ready" : "Unavailable"}
            </StatusPill>
          </div>
          {readiness ? (
            <dl className="system-grid">
              <div>
                <dt>Database</dt>
                <dd>{readiness.database_status}</dd>
              </div>
              <div>
                <dt>Cache</dt>
                <dd>{readiness.cache_status}</dd>
              </div>
              <div>
                <dt>Schema</dt>
                <dd>{readiness.schema_revision ?? "Unknown"}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{readiness.environment}</dd>
              </div>
            </dl>
          ) : (
            <div className="state-message state-message--error" role="status">
              <strong>Platform status is temporarily unavailable.</strong>
              <span>{readinessResult.ok ? "No readiness data returned." : readinessResult.message}</span>
              <Link href="/">Retry status check</Link>
            </div>
          )}
        </Panel>
      </section>

      <Panel labelledBy="sources-heading">
        <div className="panel-heading-row">
          <div>
            <p className="panel-kicker">Freshness</p>
            <h2 id="sources-heading">Source coverage</h2>
          </div>
          {sourcesResult.ok && sourcesResult.value.meta.stale ? (
            <StatusPill tone="warning">Stale response</StatusPill>
          ) : null}
        </div>
        {!sourcesResult.ok ? (
          <div className="state-message state-message--error" role="status">
            <strong>Source details could not be loaded.</strong>
            <span>{sourcesResult.message}</span>
            <Link href="/">Try again</Link>
          </div>
        ) : sources.length === 0 ? (
          <div className="state-message" role="status">
            <strong>No source status has been published yet.</strong>
            <span>The interface remains available while the first data generation completes.</span>
          </div>
        ) : (
          <div className="source-list">
            {sources.map((source) => (
              <article className="source-row" key={source.source}>
                <div>
                  <h3>{source.source.replaceAll("-", " ")}</h3>
                  <p>{source.detail || "No provider warnings reported."}</p>
                </div>
                <div className="source-meta">
                  <StatusPill tone={sourceTone(source.freshness_status)}>
                    {source.freshness_status}
                  </StatusPill>
                  <span>{source.watermark || "No watermark"}</span>
                </div>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </main>
  );
}
