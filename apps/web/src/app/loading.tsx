export default function Loading() {
  return (
    <main id="main-content" className="page-stack" aria-busy="true" aria-label="Loading page">
      <div className="skeleton skeleton--header" />
      <div className="hero-grid">
        <div className="skeleton skeleton--panel" />
        <div className="skeleton skeleton--panel" />
      </div>
      <span className="sr-only">Loading All Rise data</span>
    </main>
  );
}
