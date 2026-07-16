"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const primary = [
  ["Games", "/games"],
  ["Matchups", "/matchups"],
  ["Advanced HVP", "/research/batter-vs-pitcher"],
  ["Streaks", "/streaks"],
] as const;

const analysis = [
  ["Players", "/players"],
  ["Player stats", "/stats/players"],
  ["Team stats", "/stats/teams"],
  ["Weather", "/weather"],
  ["Methodology", "/methodology"],
] as const;

function NavigationLink({ item }: Readonly<{ item: readonly [string, string] }>) {
  const pathname = usePathname();
  const [label, href] = item;
  const active = pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
  return (
    <Link aria-current={active ? "page" : undefined} href={href}>
      {label}
    </Link>
  );
}

export function SiteNavigation() {
  return (
    <header className="site-header">
      <div className="nav-shell">
        <Link className="brand" href="/" aria-label="All Rise Analytics home">
          <span className="brand-mark" aria-hidden="true">AR</span>
          <span>
            <strong>All Rise</strong>
            <small>Analytics</small>
          </span>
        </Link>
        <nav className="desktop-nav" aria-label="Primary navigation">
          {primary.map((item) => <NavigationLink item={item} key={item[1]} />)}
          <details className="nav-more">
            <summary>More</summary>
            <div>
              {analysis.map((item) => <NavigationLink item={item} key={item[1]} />)}
            </div>
          </details>
        </nav>
        <details className="mobile-nav">
          <summary aria-label="Open navigation">Menu</summary>
          <nav aria-label="Mobile navigation">
            {[...primary, ...analysis].map((item) => (
              <NavigationLink item={item} key={item[1]} />
            ))}
          </nav>
        </details>
      </div>
    </header>
  );
}
