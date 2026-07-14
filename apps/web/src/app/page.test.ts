import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { isEnvelope } from "../lib/api";
import { canonicalDate, safeFilter, shiftDate } from "../lib/date-state";
import { safeGroup, safePlayerId, safeRole, safeSeason } from "../lib/research-state";
import { buildLegacyUrl, canonicalState, resolveLegacyRoute } from "../lib/route-state";

describe("Phase 7 route state", () => {
  it("preserves canonical state when handing a game to the legacy view", () => {
    const route = resolveLegacyRoute(["games", "746123"]);
    expect(route).not.toBeNull();
    const state = canonicalState(
      route!,
      { date: "2026-07-13", team: "NYY", ignored: "unsafe" },
      ["games", "746123"],
    );
    expect(state).toEqual({ date: "2026-07-13", team: "NYY", game_pk: "746123" });
    const url = new URL(buildLegacyUrl("http://localhost:8501", route!, state));
    expect(url.searchParams.get("view")).toBe("Games");
    expect(url.searchParams.get("game_pk")).toBe("746123");
    expect(url.searchParams.has("ignored")).toBe(false);
  });

  it("maps advanced HVP without accepting arbitrary query state", () => {
    const route = resolveLegacyRoute(["research", "batter-vs-pitcher"]);
    expect(route?.title).toBe("Advanced HVP");
    const state = canonicalState(route!, {
      batter: "592450",
      pitcher: "660271",
      callback: "javascript:alert(1)",
    });
    const url = new URL(buildLegacyUrl("https://legacy.example.test", route!, state));
    expect(url.searchParams.get("matchup_table")).toBe("Advanced HVP");
    expect(url.searchParams.get("batter")).toBe("592450");
    expect(url.searchParams.has("callback")).toBe(false);
  });

  it("rejects unknown routes and strips control characters", () => {
    expect(resolveLegacyRoute(["admin"])).toBeNull();
    const route = resolveLegacyRoute(["weather"]);
    expect(canonicalState(route!, { date: "2026-07-13\u0000bad" })).toEqual({
      date: "2026-07-13bad",
    });
  });

  it("preserves pitcher-opponent state and recognizes every migrated analytics route", () => {
    const opponent = resolveLegacyRoute(["matchups", "pitcher-vs-opponent"]);
    expect(canonicalState(opponent!, { pitcher: "543037", team: "NYY", season: "2026" }))
      .toEqual({ pitcher: "543037", team: "NYY", season: "2026" });
    expect(resolveLegacyRoute(["matchups", "bullpen"])?.title).toBe("Projected bullpen");
    expect(resolveLegacyRoute(["streaks"])?.title).toBe("Streaks");
    expect(resolveLegacyRoute(["stats", "players"])?.title).toBe("Player stats");
    expect(resolveLegacyRoute(["stats", "teams"])?.title).toBe("Team stats");
  });
});

describe("API envelope guard", () => {
  it("accepts generated envelope structure and rejects malformed payloads", () => {
    expect(isEnvelope({ data: [], meta: { request_id: "request_1", stale: false } })).toBe(true);
    expect(isEnvelope({ data: [] })).toBe(false);
    expect(isEnvelope(null)).toBe(false);
  });
});

describe("visual continuity", () => {
  it("uses the original website palette without orange accents", () => {
    const tokens = readFileSync(
      new URL("../../../../packages/ui/src/tokens.css", import.meta.url),
      "utf8",
    );
    const globalStyles = readFileSync(
      new URL("../styles/globals.css", import.meta.url),
      "utf8",
    );
    const styles = `${tokens}\n${globalStyles}`.toLowerCase();

    expect(styles).toContain("#06172b");
    expect(styles).toContain("#f3f5f7");
    expect(styles).not.toMatch(/#(?:f28a27|e47717|c74312|f6a85[0-9a-f]?|9a5b13|fff8e8)/);
    expect(styles).not.toContain("--ar-orange");
  });

  it("ships native accessible pages for every remaining Phase 7 route", () => {
    const pages = [
      "research/batter-vs-pitcher/page.tsx",
      "matchups/pitcher-vs-opponent/page.tsx",
      "matchups/bullpen/page.tsx",
      "streaks/page.tsx",
      "stats/players/page.tsx",
      "stats/teams/page.tsx",
    ];
    for (const page of pages) {
      const source = readFileSync(new URL(page, import.meta.url), "utf8");
      expect(source).toContain('id="main-content"');
      expect(source).toMatch(/<h2|PageHeader/);
      expect(source).not.toContain("LegacyFallback");
    }
  });
});

describe("slate URL state", () => {
  it("keeps valid dates stable and shifts across month boundaries", () => {
    expect(canonicalDate("2026-07-13")).toBe("2026-07-13");
    expect(shiftDate("2026-07-01", -1)).toBe("2026-06-30");
    expect(shiftDate("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("rejects impossible dates and strips control characters from filters", () => {
    expect(canonicalDate("2026-02-31")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(canonicalDate("2026-02-31")).not.toBe("2026-02-31");
    expect(safeFilter("NY\u0000Y", 5)).toBe("NYY");
  });
});

describe("research URL state", () => {
  it("accepts bounded player, season, role, and group values", () => {
    expect(safePlayerId("592450")).toBe("592450");
    expect(safeSeason("2026")).toBe(2026);
    expect(safeRole("two-way")).toBe("two-way");
    expect(safeGroup("pitching")).toBe("pitching");
  });

  it("fails closed for invalid research state", () => {
    expect(safePlayerId("592450<script>")).toBe("");
    expect(safeSeason("3000")).toBeUndefined();
    expect(safeRole("catcher")).toBeUndefined();
    expect(safeGroup("unknown")).toBe("batting");
  });
});
