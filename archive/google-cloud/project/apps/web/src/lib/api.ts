import type {
  AdvancedMatchup,
  ApiEnvelope,
  BullpenProjection,
  DataStatus,
  Game,
  Matchup,
  Player,
  PlayerLeaderboard,
  PlayerProfile,
  PitcherOpponent,
  Readiness,
  Weather,
  Streak,
  TeamLeaderboard,
  LiveGame,
} from "@all-rise/shared-types";

type ApiSuccess<T> = { ok: true; value: ApiEnvelope<T>; cacheStatus: string | null };
type ApiFailure = { ok: false; message: string; status: number | null };
export type ApiResult<T> = ApiSuccess<T> | ApiFailure;

const API_BASE_URL = (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(2_500),
    });
    if (!response.ok) {
      return { ok: false, status: response.status, message: `Request failed (${response.status}).` };
    }
    const value: unknown = await response.json();
    if (!isEnvelope<T>(value)) {
      return { ok: false, status: response.status, message: "The API returned an invalid response." };
    }
    return { ok: true, value, cacheStatus: response.headers.get("x-cache-status") };
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return {
      ok: false,
      status: null,
      message: timedOut ? "The status check timed out." : "The API could not be reached.",
    };
  }
}

export function isEnvelope<T>(value: unknown): value is ApiEnvelope<T> {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return "data" in candidate && Boolean(candidate.meta) && typeof candidate.meta === "object";
}

export function getReadiness() {
  return apiGet<Readiness>("/ready");
}

export function getDataStatus() {
  return apiGet<DataStatus[]>("/api/v1/data-status?limit=20");
}

export function getGames(filters: {
  date: string;
  team?: string;
  status?: string;
  cursor?: string;
}) {
  const query = new URLSearchParams({ date: filters.date, limit: "50" });
  if (filters.team) query.set("team", filters.team);
  if (filters.status) query.set("status", filters.status);
  if (filters.cursor) query.set("cursor", filters.cursor);
  return apiGet<Game[]>(`/api/v1/games?${query}`);
}

export function getGame(gameId: string) {
  return apiGet<Game>(`/api/v1/games/${encodeURIComponent(gameId)}`);
}

export function getWeather(filters: { date: string; gameId?: string }) {
  const query = new URLSearchParams({ date: filters.date, limit: "50" });
  if (filters.gameId) query.set("game_id", filters.gameId);
  return apiGet<Weather[]>(`/api/v1/weather?${query}`);
}

export function getGameWeather(gameId: string) {
  return apiGet<Weather>(`/api/v1/games/${encodeURIComponent(gameId)}/weather`);
}

export function getLiveGame(gameId: string) {
  return apiGet<LiveGame>(`/api/v1/games/${encodeURIComponent(gameId)}/live`);
}

export function getPlayers(filters: {
  query?: string;
  role?: "batter" | "pitcher" | "two-way";
  season?: number;
  cursor?: string;
}) {
  const query = new URLSearchParams({ limit: "40" });
  if (filters.query) query.set("query", filters.query);
  if (filters.role) query.set("role", filters.role);
  if (filters.season) query.set("season", String(filters.season));
  if (filters.cursor) query.set("cursor", filters.cursor);
  return apiGet<Player[]>(`/api/v1/players?${query}`);
}

export function getPlayerProfile(
  playerId: string,
  filters: { season?: number; group: "batting" | "pitching" },
) {
  const query = new URLSearchParams({ group: filters.group, limit: "25" });
  if (filters.season) query.set("season", String(filters.season));
  return apiGet<PlayerProfile>(
    `/api/v1/players/${encodeURIComponent(playerId)}?${query}`,
  );
}

export function getBatterPitcherMatchup(filters: {
  batterId: string;
  pitcherId: string;
  season?: number;
}) {
  const query = new URLSearchParams({
    batter_id: filters.batterId,
    pitcher_id: filters.pitcherId,
    limit: "25",
  });
  if (filters.season) query.set("season", String(filters.season));
  return apiGet<Matchup>(`/api/v1/matchups/batter-vs-pitcher?${query}`);
}

export function getAdvancedMatchup(filters: {
  batterId: string;
  pitcherId: string;
  season?: number;
}) {
  const query = new URLSearchParams({
    batter_id: filters.batterId,
    pitcher_id: filters.pitcherId,
    limit: "25",
  });
  if (filters.season) query.set("season", String(filters.season));
  return apiGet<AdvancedMatchup>(`/api/v1/research/batter-vs-pitcher?${query}`);
}

export function getPitcherOpponent(filters: {
  pitcherId: string;
  team?: string;
  season?: number;
}) {
  const query = new URLSearchParams({ pitcher_id: filters.pitcherId, limit: "25" });
  if (filters.team) query.set("team", filters.team);
  if (filters.season) query.set("season", String(filters.season));
  return apiGet<PitcherOpponent>(`/api/v1/matchups/pitcher-vs-opponent?${query}`);
}

export function getBullpenProjection(filters: {
  gameId: string;
  team?: string;
  batterId?: string;
}) {
  const query = new URLSearchParams({ game_id: filters.gameId });
  if (filters.team) query.set("team", filters.team);
  if (filters.batterId) query.set("batter_id", filters.batterId);
  return apiGet<BullpenProjection[]>(`/api/v1/matchups/bullpen?${query}`);
}

export function getStreaks(filters: { date?: string; group: string; metric: string }) {
  const query = new URLSearchParams({ group: filters.group, metric: filters.metric, limit: "50" });
  if (filters.date) query.set("date", filters.date);
  return apiGet<Streak[]>(`/api/v1/streaks?${query}`);
}

export function getPlayerLeaderboard(filters: {
  season?: number;
  group: string;
  sort: string;
  query?: string;
}) {
  const query = new URLSearchParams({ group: filters.group, sort: filters.sort, limit: "75" });
  if (filters.season) query.set("season", String(filters.season));
  if (filters.query) query.set("query", filters.query);
  return apiGet<PlayerLeaderboard[]>(`/api/v1/stats/players?${query}`);
}

export function getTeamLeaderboard(filters: { season?: number; group: string; sort: string }) {
  const query = new URLSearchParams({ group: filters.group, sort: filters.sort, limit: "30" });
  if (filters.season) query.set("season", String(filters.season));
  return apiGet<TeamLeaderboard[]>(`/api/v1/stats/teams?${query}`);
}
