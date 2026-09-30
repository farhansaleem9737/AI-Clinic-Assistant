import { CalendarDays } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { listAppointments } from "../../services/appointmentService";
import { monthBounds } from "../../utils/calendar";
import { isoDateIn } from "../../utils/datetime";
import Alert from "../Alert";
import MonthCalendar from "../MonthCalendar";

const HIDDEN = ["cancelled", "no_show"];
const UNCONFIRMED = ["requested", "scheduled"];

/**
 * "My Schedule": a month view with a dot on each day the caller has an
 * appointment (green once confirmed or under way, amber while only
 * scheduled). Clicking a marked day opens that day in the appointment list.
 */
export default function AppointmentCalendar({ title = "My Schedule" }) {
  const navigate = useNavigate();
  const today = isoDateIn(new Date());
  const [month, setMonth] = useState(today.slice(0, 7));
  const { first, last } = monthBounds(month);
  const { data, error } = useFetch(() => listAppointments({ date_from: first, date_to: last, page_size: 100 }), [month]);

  const marks = {};
  for (const a of data?.items ?? []) {
    if (HIDDEN.includes(a.status)) continue;
    const day = isoDateIn(a.starts_at, a.timezone);
    const tone = UNCONFIRMED.includes(a.status) ? "warn" : "ok";
    marks[day] = marks[day] === "ok" ? "ok" : tone;
  }

  return (
    <section className="card" aria-label={title}>
      <div className="section-head">
        <CalendarDays className="icon" size={20} aria-hidden="true" />
        <h3>{title}</h3>
      </div>
      <Alert>{error}</Alert>
      <MonthCalendar
        month={month}
        today={today}
        marks={marks}
        onMonthChange={setMonth}
        onSelectDay={(day) => navigate(`/appointments?date=${day}`)}
      />
    </section>
  );
}
