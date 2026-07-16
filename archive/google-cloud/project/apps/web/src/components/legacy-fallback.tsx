export function LegacyFallback({
  href,
  label,
}: Readonly<{ href: string; label: string }>) {
  return (
    <a className="button button--secondary" href={href}>
      Open {label} in legacy view
    </a>
  );
}
