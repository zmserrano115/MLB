import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main-content" className="centered-state">
      <p className="eyebrow">404</p>
      <h1>That page is out of the zone.</h1>
      <p>The route is not part of the All Rise migration map.</p>
      <Link className="button button--primary" href="/">Return home</Link>
    </main>
  );
}
