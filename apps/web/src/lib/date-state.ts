const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function defaultBaseballDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Denver",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export function canonicalDate(value: string | string[] | undefined) {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (!candidate || !ISO_DATE.test(candidate)) return defaultBaseballDate();
  const parsed = new Date(`${candidate}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== candidate
    ? defaultBaseballDate()
    : candidate;
}

export function shiftDate(value: string, days: number) {
  const parsed = new Date(`${value}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

export function displayDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC",
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T00:00:00Z`));
}

export function safeFilter(value: string | string[] | undefined, maxLength = 64) {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate?.trim().slice(0, maxLength).replace(/[\u0000-\u001f\u007f]/g, "") || "";
}
