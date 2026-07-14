"use client";

import type { ApiEnvelope, LiveGame } from "@all-rise/shared-types";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

type Tab = "live" | "stats" | "box-score";
type Team = { name?: string; abbreviation?: string; runs?: number; hits?: number; errors?: number };
type Person = { id?: number; name?: string; headshot_url?: string };
type Play = { play_id?: string | number; description?: string; result_type?: string; inning?: number; half_inning?: string; contact?: { launch_speed?: number; launch_angle?: number; total_distance?: number; x?: number; y?: number } | null };

export function LiveGameCenter({
  initial,
  initialStale,
  endpoint,
  initialTab,
}: {
  initial: LiveGame;
  initialStale: boolean;
  endpoint: string;
  initialTab: Tab;
}) {
  const [snapshot, setSnapshot] = useState(initial);
  const [stale, setStale] = useState(initialStale);
  const [connection, setConnection] = useState<"current" | "reconnecting">("current");
  const version = useRef(initial.version);
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const tab: Tab = requestedTab === "stats" || requestedTab === "box-score" || requestedTab === "live"
    ? requestedTab
    : initialTab;

  useEffect(() => {
    if (snapshot.is_final) return;
    let disposed = false;
    const poll = async () => {
      try {
        const url = `${endpoint}?since=${encodeURIComponent(version.current)}`;
        const response = await fetch(url, { headers: { accept: "application/json" }, cache: "no-store" });
        if (response.status === 304) {
          if (!disposed) setConnection("current");
          return;
        }
        if (!response.ok) throw new Error(String(response.status));
        const envelope = (await response.json()) as ApiEnvelope<LiveGame>;
        if (!disposed) {
          version.current = envelope.data.version;
          setSnapshot(envelope.data);
          setStale(envelope.meta.stale);
          setConnection("current");
        }
      } catch {
        if (!disposed) {
          setConnection("reconnecting");
          setStale(true);
        }
      }
    };
    const timer = window.setInterval(poll, 5_000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [endpoint, snapshot.is_final]);

  const teams = snapshot.teams as Record<string, Team>;
  const count = snapshot.count as Record<string, number | null>;
  const matchup = snapshot.matchup as Record<string, Person | string | null>;
  const plays = snapshot.recent_plays as Play[];
  const latestPlay = plays.at(-1);
  const tabs: { id: Tab; label: string }[] = [
    { id: "live", label: "Live" }, { id: "stats", label: "Contact" }, { id: "box-score", label: "Box score" },
  ];
  const observed = useMemo(() => new Date(snapshot.observed_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" }), [snapshot.observed_at]);

  function selectTab(next: Tab) {
    const query = new URLSearchParams(searchParams.toString());
    query.set("tab", next);
    router.replace(`?${query}`, { scroll: false });
  }

  return (
    <section className="live-center" aria-labelledby="live-center-heading">
      <div className="live-center__status" aria-live="polite">
        <span className={`live-dot${snapshot.is_final ? " live-dot--final" : ""}`} aria-hidden="true" />
        <strong>{snapshot.is_final ? "Final" : snapshot.detailed_state}</strong>
        <span>{stale || connection === "reconnecting" ? "Persisted snapshot · reconnecting" : `Updated ${observed}`}</span>
      </div>
      <h2 id="live-center-heading" className="sr-only">Live Game Center</h2>
      <div className="live-scoreboard" key={`${snapshot.version}-score`}>
        <TeamScore label="Away" team={teams.away} />
        <div className="live-inning"><strong>{snapshot.half_inning || ""} {snapshot.inning_ordinal || ""}</strong><span>{count.outs ?? 0} out{count.outs === 1 ? "" : "s"}</span></div>
        <TeamScore label="Home" team={teams.home} />
      </div>
      <div className="live-tabs" role="tablist" aria-label="Game Center views">
        {tabs.map((item) => <button key={item.id} role="tab" aria-selected={tab === item.id} onClick={() => selectTab(item.id)}>{item.label}</button>)}
      </div>
      {tab === "live" && <LiveTab snapshot={snapshot} matchup={matchup} count={count} latestPlay={latestPlay} plays={plays} />}
      {tab === "stats" && <ContactTab plays={plays} />}
      {tab === "box-score" && <BoxScore boxscore={snapshot.boxscore as Record<string, unknown>} />}
    </section>
  );
}

function TeamScore({ label, team }: { label: string; team?: Team }) {
  return <div className="live-team"><span>{label}</span><strong>{team?.abbreviation || team?.name || label}</strong><b>{team?.runs ?? 0}</b><small>{team?.hits ?? 0} H · {team?.errors ?? 0} E</small></div>;
}

function LiveTab({ snapshot, matchup, count, latestPlay, plays }: { snapshot: LiveGame; matchup: Record<string, Person | string | null>; count: Record<string, number | null>; latestPlay?: Play; plays: Play[] }) {
  const bases = snapshot.bases as Record<string, boolean>;
  return <div className="live-grid" role="tabpanel">
    <div className="live-field-card">
      <div className="base-diamond" aria-label={`Runners: first ${bases.first ? "occupied" : "empty"}, second ${bases.second ? "occupied" : "empty"}, third ${bases.third ? "occupied" : "empty"}`}>
        <i className={`base base--second ${bases.second ? "is-on" : ""}`} /><i className={`base base--third ${bases.third ? "is-on" : ""}`} /><i className={`base base--first ${bases.first ? "is-on" : ""}`} />
      </div>
      <div className="count-strip"><span>{count.balls ?? 0}-{count.strikes ?? 0}</span><small>{count.fouls ?? 0} fouls</small></div>
      <dl className="live-matchup"><div><dt>At bat</dt><dd>{(matchup.batter as Person | null)?.name || "Awaiting batter"}</dd></div><div><dt>Pitching</dt><dd>{(matchup.pitcher as Person | null)?.name || "Awaiting pitcher"}</dd></div></dl>
    </div>
    <div className="live-play-card" key={String(latestPlay?.play_id || snapshot.version)}><p className="panel-kicker">Latest play</p><h3>{latestPlay?.description || "Waiting for the next pitch"}</h3><ol className="play-feed">{plays.slice().reverse().map((play, index) => <li key={String(play.play_id ?? index)}><span>{play.half_inning} {play.inning}</span>{play.description}</li>)}</ol></div>
  </div>;
}

function ContactTab({ plays }: { plays: Play[] }) {
  const contacts = plays.filter((play) => play.contact?.launch_speed != null);
  return <div className="contact-list" role="tabpanel">{contacts.length ? contacts.map((play, index) => <article key={String(play.play_id ?? index)}><strong>{play.description}</strong><span>{play.contact?.launch_speed?.toFixed(1)} mph · {play.contact?.launch_angle?.toFixed(0)}° · {play.contact?.total_distance?.toFixed(0) ?? "—"} ft</span></article>) : <p>No tracked contact in the recent-play window.</p>}</div>;
}

function BoxScore({ boxscore }: { boxscore: Record<string, unknown> }) {
  return <div className="box-score-grid" role="tabpanel">{(["away", "home"] as const).map((side) => { const team = (boxscore[side] || {}) as { batting?: { player?: Person; position?: string; stats?: Record<string, string | number> }[] }; return <section key={side}><h3>{side === "away" ? "Away" : "Home"} batting</h3><div className="table-scroll"><table><thead><tr><th>Player</th><th>AB</th><th>H</th><th>RBI</th></tr></thead><tbody>{(team.batting || []).map((row, index) => <tr key={row.player?.id ?? index}><th>{row.player?.name || "Player"} <small>{row.position}</small></th><td>{row.stats?.atBats ?? "—"}</td><td>{row.stats?.hits ?? "—"}</td><td>{row.stats?.rbi ?? "—"}</td></tr>)}</tbody></table></div></section>; })}</div>;
}
