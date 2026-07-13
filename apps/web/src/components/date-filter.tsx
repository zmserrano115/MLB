import Link from "next/link";

import { shiftDate } from "../lib/date-state";

export function DateFilter({
  action,
  date,
  team,
  status,
  showGameFilters = false,
}: Readonly<{
  action: string;
  date: string;
  team?: string;
  status?: string;
  showGameFilters?: boolean;
}>) {
  return (
    <form className="filter-bar" action={action} method="get">
      <Link className="date-step" href={`${action}?date=${shiftDate(date, -1)}`}>
        Previous day
      </Link>
      <label>
        <span>Date</span>
        <input type="date" name="date" defaultValue={date} />
      </label>
      {showGameFilters ? (
        <>
          <label>
            <span>Team</span>
            <input
              name="team"
              defaultValue={team}
              maxLength={5}
              placeholder="NYY"
              pattern="[A-Za-z0-9]+"
            />
          </label>
          <label>
            <span>Status</span>
            <select name="status" defaultValue={status}>
              <option value="">All</option>
              <option value="Preview">Preview</option>
              <option value="Live">Live</option>
              <option value="Final">Final</option>
            </select>
          </label>
        </>
      ) : null}
      <button className="button button--primary" type="submit">Apply</button>
      <Link className="date-step" href={`${action}?date=${shiftDate(date, 1)}`}>
        Next day
      </Link>
    </form>
  );
}
