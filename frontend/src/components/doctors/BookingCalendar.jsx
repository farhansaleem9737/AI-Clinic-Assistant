import { ChevronLeft, ChevronRight } from "lucide-react";
import { addMonths, longDate, monthGrid, monthLabel } from "../../utils/calendar";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Month calendar for booking. `available` maps "YYYY-MM-DD" (the clinic's
 * local date, as returned by the API) to the number of free times that day;
 * only those days can be chosen. Past days, days off and fully booked days
 * simply have no entry.
 */
export default function BookingCalendar({ month, today, available, selected, canGoBack, canGoForward, onMonthChange, onSelect }) {
  return (
    <div className="booking-calendar">
      <div className="calendar-head">
        <button
          type="button"
          className="secondary"
          aria-label="Previous month"
          disabled={!canGoBack}
          onClick={() => onMonthChange(addMonths(month, -1))}
        >
          <ChevronLeft size={18} aria-hidden="true" />
        </button>
        <strong aria-live="polite">{monthLabel(month)}</strong>
        <button
          type="button"
          className="secondary"
          aria-label="Next month"
          disabled={!canGoForward}
          onClick={() => onMonthChange(addMonths(month, 1))}
        >
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      </div>
      <div className="calendar" role="group" aria-label={`Dates in ${monthLabel(month)}`}>
        {DOW.map((d) => (
          <div key={d} className="dow" aria-hidden="true">
            {d}
          </div>
        ))}
        {monthGrid(month).map(({ date, inMonth }) => {
          const day = Number(date.slice(8));
          if (!inMonth) {
            return (
              <div key={date} className="cell outside" aria-hidden="true">
                {day}
              </div>
            );
          }
          const count = available[date] ?? 0;
          const isSelected = count > 0 && date === selected;
          const label = [
            longDate(date),
            date === today ? "today" : null,
            count ? `${count} ${count === 1 ? "time" : "times"} available` : "no available times",
          ]
            .filter(Boolean)
            .join(", ");
          return (
            <button
              type="button"
              key={date}
              className={`cell${count ? " available" : ""}${isSelected ? " selected" : ""}${date === today ? " today" : ""}`}
              disabled={!count}
              aria-pressed={count ? isSelected : undefined}
              aria-label={label}
              title={count ? undefined : "No available times"}
              onClick={() => onSelect(date)}
            >
              {day}
              {count > 0 && <span className="avail-dot" aria-hidden="true" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
