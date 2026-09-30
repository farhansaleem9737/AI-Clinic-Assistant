import { ChevronLeft, ChevronRight } from "lucide-react";
import { addMonths, monthGrid, monthLabel } from "../utils/calendar";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Month view. `marks` maps "YYYY-MM-DD" to a tone ("ok" | "warn") for days
 * that have appointments; those days are clickable.
 */
export default function MonthCalendar({ month, today, marks = {}, onMonthChange, onSelectDay }) {
  return (
    <div>
      <div className="calendar-head">
        <button type="button" className="secondary" aria-label="Previous month" onClick={() => onMonthChange(addMonths(month, -1))}>
          <ChevronLeft size={16} />
        </button>
        <strong>{monthLabel(month)}</strong>
        <button type="button" className="secondary" aria-label="Next month" onClick={() => onMonthChange(addMonths(month, 1))}>
          <ChevronRight size={16} />
        </button>
        <button type="button" className="secondary" onClick={() => onMonthChange(today.slice(0, 7))}>
          Today
        </button>
      </div>
      <div className="calendar">
        {DOW.map((d) => (
          <div key={d} className="dow">
            {d}
          </div>
        ))}
        {monthGrid(month).map(({ date, inMonth }) => {
          const tone = marks[date];
          const className = `cell${inMonth ? "" : " outside"}${date === today ? " today" : ""}`;
          const day = Number(date.slice(8));
          return tone ? (
            <button
              type="button"
              key={date}
              className={className}
              aria-label={`${date}, has appointments`}
              onClick={() => onSelectDay?.(date)}
            >
              {day}
              <span className={`dot ${tone === "warn" ? "warn" : ""}`} />
            </button>
          ) : (
            <div key={date} className={className}>
              {day}
            </div>
          );
        })}
      </div>
    </div>
  );
}
