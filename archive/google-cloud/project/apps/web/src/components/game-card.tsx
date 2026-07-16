import type { Game } from "@all-rise/shared-types";
import { StatusPill } from "@all-rise/ui";
import Link from "next/link";

function gameTime(value: string | null | undefined) {
  if (!value) return "Time TBD";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Denver",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}

function teamLabel(name: string, abbreviation: string | null | undefined) {
  return abbreviation || name;
}

export function GameCard({ game }: Readonly<{ game: Game }>) {
  const final = game.status?.toLowerCase().includes("final");
  const href = `/games/${encodeURIComponent(game.game_id)}?date=${game.game_date}`;
  return (
    <article className="game-card">
      <header>
        <span>{gameTime(game.game_time_utc)}</span>
        <StatusPill tone={final ? "healthy" : "neutral"}>{game.status || "Scheduled"}</StatusPill>
      </header>
      <div className="game-team-row">
        <strong>{teamLabel(game.away_team.name, game.away_team.abbreviation)}</strong>
        <span>{game.away_team.name}</span>
        <b>{game.away_team.score ?? "—"}</b>
      </div>
      <div className="game-team-row">
        <strong>{teamLabel(game.home_team.name, game.home_team.abbreviation)}</strong>
        <span>{game.home_team.name}</span>
        <b>{game.home_team.score ?? "—"}</b>
      </div>
      <dl className="pitcher-pair">
        <div><dt>Away probable</dt><dd>{game.away_probable_pitcher?.name || "TBD"}</dd></div>
        <div><dt>Home probable</dt><dd>{game.home_probable_pitcher?.name || "TBD"}</dd></div>
      </dl>
      <footer>
        <span>{game.venue?.name || "Venue TBD"}</span>
        <Link href={href}>Game details</Link>
      </footer>
    </article>
  );
}
