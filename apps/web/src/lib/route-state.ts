export type QueryValue = string | string[] | undefined;
export type QueryState = Record<string, QueryValue>;

export type LegacyRoute = {
  title: string;
  description: string;
  view: string;
  allowedState: readonly string[];
  legacyDefaults?: Readonly<Record<string, string>>;
};

const routeDefinitions: Readonly<Record<string, LegacyRoute>> = {
  games: {
    title: "Games",
    description: "Daily slate, probable pitchers, scores, and game context.",
    view: "Games",
    allowedState: ["date", "team", "status", "game_pk", "tab"],
  },
  players: {
    title: "Player profile",
    description: "Season detail, splits, recent form, and game logs.",
    view: "Players",
    allowedState: ["player_id", "season", "group", "from", "query", "role"],
  },
  matchups: {
    title: "Matchups",
    description: "Hitter, pitcher, hand, strikeout, and bullpen matchup research.",
    view: "Matchups",
    allowedState: ["date", "game", "batter", "pitcher", "type", "team"],
  },
  "matchups/bullpen": {
    title: "Projected bullpen",
    description: "Likely relief paths, workload, availability, and batter fit.",
    view: "Matchups",
    allowedState: ["game", "batter", "team"],
    legacyDefaults: { matchup_table: "Projected Bullpen" },
  },
  "matchups/pitcher-vs-opponent": {
    title: "Pitcher vs opponent",
    description: "Opponent workload, strikeout, and game-log research.",
    view: "Matchups",
    allowedState: ["pitcher", "team", "season"],
    legacyDefaults: { matchup_table: "Pitcher Matchups" },
  },
  "research/batter-vs-pitcher": {
    title: "Advanced HVP",
    description: "Pitch sequence, contact quality, direct history, and pitch-type context.",
    view: "Matchups",
    allowedState: ["batter", "pitcher", "game", "mode", "date"],
    legacyDefaults: { matchup_table: "Advanced HVP" },
  },
  streaks: {
    title: "Streaks",
    description: "Current performance runs with schedule and game context.",
    view: "Streaks",
    allowedState: ["date", "group", "metric", "game"],
  },
  "stats/players": {
    title: "Player stats",
    description: "Sortable player leaderboards and season comparisons.",
    view: "Player Stats",
    allowedState: ["season", "group", "sort", "query"],
  },
  "stats/teams": {
    title: "Team stats",
    description: "Team-level batting, pitching, and run-environment comparisons.",
    view: "Team Stats",
    allowedState: ["season", "group", "mode", "sort"],
  },
  weather: {
    title: "Weather",
    description: "Venue forecasts and modeled hitting and pitching adjustments.",
    view: "Weather",
    allowedState: ["date", "game"],
  },
};

export function resolveLegacyRoute(segments: readonly string[]): LegacyRoute | null {
  const exact = segments.join("/");
  if (routeDefinitions[exact]) return routeDefinitions[exact];
  if (segments[0] === "games" && segments.length === 2) {
    return routeDefinitions.games;
  }
  if (segments[0] === "players" && segments.length === 2) {
    return routeDefinitions.players;
  }
  return null;
}

export function canonicalState(
  route: LegacyRoute,
  query: QueryState,
  segments: readonly string[] = [],
) {
  const state: Record<string, string> = {};
  for (const key of route.allowedState) {
    const value = firstValue(query[key]);
    if (value) state[key] = value;
  }
  if (segments[0] === "games" && segments[1]) state.game_pk = safeValue(segments[1]);
  if (segments[0] === "players" && segments[1]) state.player_id = safeValue(segments[1]);
  return state;
}

export function buildLegacyUrl(
  baseUrl: string,
  route: LegacyRoute,
  state: Readonly<Record<string, string>>,
) {
  const url = new URL(baseUrl);
  url.searchParams.set("view", route.view);
  for (const [key, value] of Object.entries(route.legacyDefaults || {})) {
    url.searchParams.set(key, value);
  }
  for (const [key, value] of Object.entries(state)) {
    url.searchParams.set(key, value);
  }
  return url.toString();
}

function firstValue(value: QueryValue) {
  return safeValue(Array.isArray(value) ? value[0] : value);
}

function safeValue(value: string | undefined) {
  if (!value) return "";
  return value.trim().slice(0, 128).replace(/[\u0000-\u001f\u007f]/g, "");
}
