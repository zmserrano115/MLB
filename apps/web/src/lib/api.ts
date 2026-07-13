import type {
  ApiEnvelope,
  DataStatus,
  Game,
  Readiness,
  Weather,
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
