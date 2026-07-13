"use client";

import Link from "next/link";

export default function ErrorPage({ reset }: Readonly<{ reset: () => void }>) {
  return (
    <main id="main-content" className="centered-state">
      <p className="eyebrow">Something changed</p>
      <h1>This view could not be loaded.</h1>
      <p>The rest of All Rise is still available. Retry this request or return to the home page.</p>
      <div className="handoff-actions">
        <button className="button button--primary" onClick={reset}>Try again</button>
        <Link className="button button--secondary" href="/">Return home</Link>
      </div>
    </main>
  );
}
