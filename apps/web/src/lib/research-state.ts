import { safeFilter } from "./date-state";

export function safePlayerId(value: string | string[] | undefined) {
  const candidate = safeFilter(value, 20);
  return /^\d+$/.test(candidate) ? candidate : "";
}

export function safeSeason(value: string | string[] | undefined) {
  const candidate = Number(safeFilter(value, 4));
  return Number.isInteger(candidate) && candidate >= 1876 && candidate <= 2200
    ? candidate
    : undefined;
}

export function safeRole(value: string | string[] | undefined) {
  const candidate = safeFilter(value, 16);
  return candidate === "batter" || candidate === "pitcher" || candidate === "two-way"
    ? candidate
    : undefined;
}

export function safeGroup(value: string | string[] | undefined) {
  return safeFilter(value, 16) === "pitching" ? "pitching" : "batting";
}
