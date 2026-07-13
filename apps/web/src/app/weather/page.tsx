import { PageHeader, Panel, StatusPill } from "@all-rise/ui";
import type { Metadata } from "next";
import Link from "next/link";

import { DateFilter } from "../../components/date-filter";
import { LegacyFallback } from "../../components/legacy-fallback";
import { getWeather } from "../../lib/api";
import { canonicalDate, displayDate, safeFilter } from "../../lib/date-state";
import { buildLegacyUrl, resolveLegacyRoute } from "../../lib/route-state";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Weather" };

type PageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function WeatherPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const date = canonicalDate(query.date);
  const gameId = safeFilter(query.game, 80);
  const result = await getWeather({ date, gameId: gameId || undefined });
  const forecasts = result.ok ? result.value.data : [];
  const legacyUrl = buildLegacyUrl(
    process.env.LEGACY_BASE_URL || "http://localhost:8501/",
    resolveLegacyRoute(["weather"])!,
    { date, ...(gameId ? { game: gameId } : {}) },
  );

  return (
    <main id="main-content" className="page-stack weather-page">
      <PageHeader
        eyebrow="Ballpark conditions"
        title="Weather"
        summary={`${displayDate(date)} — persisted venue forecasts and bounded matchup adjustments.`}
      >
        <StatusPill tone={result.ok && !result.value.meta.stale ? "healthy" : "warning"}>
          {result.ok && !result.value.meta.stale ? "Persisted data" : "Check freshness"}
        </StatusPill>
        <LegacyFallback href={legacyUrl} label="complete Weather" />
      </PageHeader>
      <DateFilter action="/weather" date={date} />

      {!result.ok || forecasts.length === 0 ? (
        <Panel className="state-panel" labelledBy="weather-state-heading">
          <p className="panel-kicker">Forecast snapshot</p>
          <h2 id="weather-state-heading">
            {!result.ok ? "Weather data could not be loaded." : "No weather snapshot is published for this slate."}
          </h2>
          <p>
            Forecast providers are never called from this page. Until the scheduled weather worker
            publishes a valid snapshot, the existing view remains the authoritative fallback.
          </p>
          <LegacyFallback href={legacyUrl} label="Weather" />
        </Panel>
      ) : (
        <section className="weather-grid" aria-label={`Weather for ${date}`}>
          {forecasts.map((forecast) => (
            <article className="weather-card" key={forecast.game_id}>
              <header>
                <div>
                  <span>{forecast.away_team.abbreviation || forecast.away_team.name}</span>
                  <strong>at</strong>
                  <span>{forecast.home_team.abbreviation || forecast.home_team.name}</span>
                </div>
                <StatusPill tone={forecast.available ? "healthy" : "neutral"}>
                  {forecast.available ? forecast.condition || "Available" : "Unavailable"}
                </StatusPill>
              </header>
              <div className="weather-reading">
                <b>{forecast.temperature_f?.toFixed(0) ?? "—"}<small>°F</small></b>
                <div><span>Wind</span><strong>{forecast.wind_speed_mph?.toFixed(0) ?? "—"} mph</strong></div>
                <div><span>Rain</span><strong>{forecast.precipitation_probability?.toFixed(0) ?? "—"}%</strong></div>
              </div>
              <footer>
                <span>{forecast.venue?.name || "Venue TBD"}</span>
                <Link href={`/games/${encodeURIComponent(forecast.game_id)}?date=${date}`}>Game context</Link>
              </footer>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
