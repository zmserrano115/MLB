import type { components } from "./openapi";

export type ApiMeta = components["schemas"]["ApiMeta"];
export type AdvancedMatchup = components["schemas"]["AdvancedMatchupData"];
export type BullpenProjection = components["schemas"]["BullpenProjectionData"];
export type DataStatus = components["schemas"]["DataStatusData"];
export type Game = components["schemas"]["GameData"];
export type Matchup = components["schemas"]["BatterPitcherMatchupData"];
export type Player = components["schemas"]["PlayerData"];
export type PlayerProfile = components["schemas"]["PlayerProfileData"];
export type PlayerLeaderboard = components["schemas"]["PlayerLeaderboardData"];
export type PitcherOpponent = components["schemas"]["PitcherOpponentData"];
export type Readiness = components["schemas"]["ReadinessData"];
export type Weather = components["schemas"]["WeatherData"];
export type Streak = components["schemas"]["StreakData"];
export type TeamLeaderboard = components["schemas"]["TeamLeaderboardData"];

export type ApiEnvelope<T> = {
  data: T;
  meta: ApiMeta;
};

export type ApiErrorEnvelope = components["schemas"]["ErrorEnvelope"];
