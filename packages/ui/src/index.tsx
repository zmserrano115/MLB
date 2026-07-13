import type { ReactNode } from "react";

export type StatusTone = "healthy" | "warning" | "danger" | "neutral";

export function StatusPill({
  children,
  tone = "neutral",
}: Readonly<{ children: ReactNode; tone?: StatusTone }>) {
  return <span className={`status-pill status-pill--${tone}`}>{children}</span>;
}

export function Panel({
  children,
  className = "",
  labelledBy,
}: Readonly<{ children: ReactNode; className?: string; labelledBy?: string }>) {
  return (
    <section className={`panel ${className}`.trim()} aria-labelledby={labelledBy}>
      {children}
    </section>
  );
}

export function PageHeader({
  eyebrow,
  title,
  summary,
  children,
}: Readonly<{
  eyebrow: string;
  title: string;
  summary: string;
  children?: ReactNode;
}>) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-summary">{summary}</p>
      </div>
      {children ? <div className="page-actions">{children}</div> : null}
    </header>
  );
}
