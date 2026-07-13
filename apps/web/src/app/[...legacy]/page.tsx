import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  buildLegacyUrl,
  canonicalState,
  resolveLegacyRoute,
  type QueryState,
} from "../../lib/route-state";

type PageProps = {
  params: Promise<{ legacy: string[] }>;
  searchParams: Promise<QueryState>;
};

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const route = resolveLegacyRoute((await params).legacy);
  return { title: route?.title || "Page not found" };
}

export default async function LegacyHandoffPage({ params, searchParams }: PageProps) {
  const segments = (await params).legacy;
  const route = resolveLegacyRoute(segments);
  if (!route) notFound();
  const state = canonicalState(route, await searchParams, segments);
  const legacyUrl = buildLegacyUrl(
    process.env.LEGACY_BASE_URL || "http://localhost:8501/",
    route,
    state,
  );

  return (
    <main id="main-content" className="page-stack">
      <PageHeader eyebrow="Migration preview" title={route.title} summary={route.description}>
        <StatusPill tone="warning">Legacy authoritative</StatusPill>
      </PageHeader>
      <Panel className="handoff-panel" labelledBy="handoff-heading">
        <div className="handoff-copy">
          <p className="panel-kicker">Context-preserving handoff</p>
          <h2 id="handoff-heading">Continue in the proven view</h2>
          <p>
            This page stays on the existing All Rise application until its API contract and
            parity checks are complete. Your supported filters are carried into that view.
          </p>
          <div className="handoff-actions">
            <a className="button button--primary" href={legacyUrl}>
              Open {route.title}
            </a>
            <Link className="button button--secondary" href="/methodology#migration">
              Why this page is staged
            </Link>
          </div>
        </div>
        <div className="state-summary" aria-label="Current route state">
          <h3>Current selection</h3>
          {Object.keys(state).length ? (
            <dl>
              {Object.entries(state).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replaceAll("_", " ")}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p>No filters selected. The legacy page will open at its default view.</p>
          )}
        </div>
      </Panel>
    </main>
  );
}
