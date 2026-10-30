import { CalendarDays, ChevronDown } from "lucide-react";
import { useRef } from "react";
import { readDay, shortDay } from "../utils/doctorAppointments";

/**
 * "Wed, Apr 23, 2026" with a calendar icon: a native date input laid over the
 * control, so clicking opens the browser's picker and the keyboard works.
 * `value` and `onChange` use "YYYY-MM-DD" calendar dates.
 */
export default function DateSelect({ value, onChange, label = "Selected date" }) {
  const input = useRef(null);
  return (
    <div className="date-select">
      <CalendarDays size={20} aria-hidden="true" />
      <span aria-hidden="true">{value ? shortDay(value) : "Choose a date"}</span>
      <ChevronDown size={16} aria-hidden="true" />
      <input
        ref={input}
        type="date"
        aria-label={label}
        value={value ?? ""}
        onChange={(e) => readDay(e.target.value) && onChange(e.target.value)}
        onClick={() => input.current?.showPicker?.()}
      />
    </div>
  );
}
