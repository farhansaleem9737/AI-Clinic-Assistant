import { CalendarDays, Clock, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { useDraft } from "../../hooks/useDraft";
import { useFetch } from "../../hooks/useFetch";
import { getPublicAvailability } from "../../services/doctorService";
import { addMonths, longDate, monthBounds, monthLabel } from "../../utils/calendar";
import { formatSlotTime, isoDateIn, timeZoneLabel } from "../../utils/datetime";
import Alert from "../Alert";
import AutoTokenPanel from "../booking/AutoTokenPanel";
import TokenRequest from "../queue/TokenRequest";
import BookingCalendar from "./BookingCalendar";

/**
 * Pick a date, then a free time, for one doctor. Every date and time comes
 * from the API (working hours − leave − bookings, booking notice applied);
 * nothing is reserved here, and the booking re-checks the time.
 *
 * `selected` is the chosen slot ({ starts_at, ends_at, timezone }) or null;
 * `onSelect` receives the new one, or null when the choice is cleared (date
 * or month changed, or the time is no longer offered). Bump `refreshKey` to
 * reload the times, e.g. after a booking conflict.
 *
 * `draftKey` (optional) keeps the month and date being looked at while the
 * user visits other pages (hooks/useDraft.js).
 *
 * `layout="panel"` (default) is the compact doctor-profile panel;
 * `layout="cards"` is the booking wizard's "Select a date" and "Available
 * times" cards. Both show unavailable times greyed out.
 *
 * The wizard (cards) books by Automatic Token by default (D120): the server
 * assigns the earliest free time on the chosen date; "Choose custom time"
 * shows the same day's times to pick from. A chosen slot carries `mode`
 * ("auto" | "custom"). `patientId`: staff booking for a patient.
 */
export default function DateTimePicker({ doctorId, selected, onSelect, refreshKey = 0, draftKey = null, layout = "panel", patientId = null }) {
  // Open on the already-chosen time (e.g. coming back from the confirm step).
  const initialDate = selected?.timezone ? isoDateIn(selected.starts_at, selected.timezone) : null;
  const [month, setMonth] = useDraft(draftKey && `${draftKey}:month`, () => (initialDate ?? isoDateIn(new Date())).slice(0, 7));
  const [pickedDate, setPickedDate] = useDraft(draftKey && `${draftKey}:picked`, initialDate);
  const [attempt, setAttempt] = useState(0); // bumped by "Try again"
  const [pickedHour, setPickedHour] = useState(null); // Date -> Hour -> Time (D117)
  const [mode, setMode] = useDraft(draftKey && `${draftKey}:mode`, "auto");
  const auto = layout === "cards" && mode === "auto";

  const { first, last } = monthBounds(month);
  const { data, loading, error } = useFetch(
    () => getPublicAvailability(doctorId, first, last),
    [doctorId, first],
    { query: "availability/public", refresh: `${attempt}:${refreshKey}` }
  );
  const current = loading ? null : data; // never show another month's times while loading

  const timezone = current?.timezone;
  const byDate = Object.fromEntries((current?.days ?? []).map((d) => [d.date, d]));
  const counts = Object.fromEntries(Object.values(byDate).map((d) => [d.date, d.slots.length]));
  // The chosen date if it has times this month, otherwise the first date that does.
  const date = pickedDate && byDate[pickedDate] ? pickedDate : (current?.days[0]?.date ?? null);
  const slots = date ? byDate[date].slots : [];
  const slot = slots.find((s) => s.starts_at === selected?.starts_at) ?? null;
  const stale = Boolean(current && selected && !slot);

  // A chosen time that is no longer offered is cleared, and the user told why: it
  // was taken meanwhile (a live update, D122, or a refresh). Changing the date or
  // month clears the choice first, so it is never "stale" for those.
  // (Automatic mode picks its own next time instead.)
  const [takenAt, setTakenAt] = useState(null);
  if (stale && !auto && takenAt !== selected.starts_at) setTakenAt(selected.starts_at);
  const takenNotice = takenAt ? "The time you picked was just booked by someone else. Please choose another time." : "";
  useEffect(() => {
    if (stale) onSelect(null);
  }, [stale, onSelect]);

  const today = isoDateIn(new Date(), timezone);
  const canGoBack = month > today.slice(0, 7);
  const canGoForward = !current?.bookable_until || month < current.bookable_until.slice(0, 7);
  const emptyMonth = current && current.days.length === 0;

  const changeMonth = (next) => {
    setMonth(next);
    setPickedDate(null);
    onSelect(null);
  };
  const choose = (s) => {
    setTakenAt(null);
    setPickedDate(date);
    onSelect({ ...s, timezone, mode: "custom" });
  };
  const switchMode = (next) => {
    if (next === mode) return;
    setMode(next);
    onSelect(null); // the other way chooses its own time
  };
  // "See <next date>" from the automatic panel, possibly in another month.
  const pickDate = (iso) => {
    setMonth(iso.slice(0, 7));
    setPickedDate(iso);
    onSelect(null);
  };
  const retry = (
    <div className="booking-error">
      <Alert>{error}</Alert>
      <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
        Try again
      </button>
    </div>
  );

  const calendar = (
    <BookingCalendar
      month={month}
      today={today}
      available={counts}
      selected={date}
      canGoBack={canGoBack}
      canGoForward={canGoForward}
      onMonthChange={changeMonth}
      onSelect={(d) => {
        setPickedDate(d);
        setPickedHour(null);
        onSelect(null);
      }}
    />
  );

  // Free and greyed-out (taken or too soon) times together, in time order.
  const board = date
    ? [
        ...slots.map((s) => ({ ...s, free: true })),
        ...(byDate[date].unavailable ?? []).map((s) => ({ ...s, free: false })),
      ].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))
    : [];

  // The day's times by clock hour: pick an hour, then a time within it.
  const hourOf = (s) => new Intl.DateTimeFormat("en-US", { timeZone: timezone, hour: "numeric", hourCycle: "h23" }).format(new Date(s.starts_at));
  const hours = [...new Set(board.map(hourOf))];
  const freeIn = (h) => board.filter((s) => s.free && hourOf(s) === h).length;
  const hour =
    pickedHour && hours.includes(pickedHour)
      ? pickedHour
      : (slot && hourOf(slot)) || hours.find((h) => freeIn(h) > 0) || hours[0];
  const hourLabel = (h) => new Intl.DateTimeFormat("en-US", { hour: "numeric" }).format(new Date(2000, 0, 1, Number(h)));
  const fifo = current?.scheduling_mode === "fifo";

  const emptyMonthMessage = (
    <div className="booking-empty">
      <p className="muted">No appointment times are available in {monthLabel(month)}.</p>
      {canGoForward && (
        <button type="button" className="secondary" onClick={() => changeMonth(addMonths(month, 1))}>
          Show {monthLabel(addMonths(month, 1))}
        </button>
      )}
    </div>
  );

  if (layout === "cards") {
    return (
      <div className="datetime-cards">
        <section className="card calendar-card" aria-labelledby="pick-date-title">
          <div className="card-title">
            <CalendarDays className="icon" size={26} aria-hidden="true" />
            <div>
              <h3 id="pick-date-title">Select a date</h3>
              <p className="muted">Choose a date for your appointment.</p>
            </div>
          </div>
          {error ? (
            retry
          ) : (
            <>
              {calendar}
              <ul className="calendar-legend" aria-label="Calendar key">
                <li>
                  <span className="legend-dot selected" aria-hidden="true" /> Selected date
                </li>
                <li>
                  <span className="legend-dot available" aria-hidden="true" /> Available
                </li>
                <li>
                  <span className="legend-dot unavailable" aria-hidden="true" /> Unavailable
                </li>
              </ul>
            </>
          )}
        </section>

        <section className="card times-card" aria-labelledby="pick-time-title">
          <div className="card-title">
            <Clock className="icon" size={26} aria-hidden="true" />
            <div>
              <h3 id="pick-time-title">{fifo ? "Get a token" : auto ? "Your appointment time" : "Available times"}</h3>
              <p className="muted">
                {fifo ? (
                  "Seen in arrival order."
                ) : auto ? (
                  "We'll assign the next available appointment time."
                ) : date ? (
                  <>
                    Select a time slot for <span className="accent-text">{longDate(date)}</span>.
                  </>
                ) : (
                  "Select a date to see its times."
                )}
              </p>
            </div>
          </div>
          {!fifo && (
            <div className="booking-mode" role="radiogroup" aria-label="How to choose the time">
              <label className={auto ? "booking-mode-option selected" : "booking-mode-option"}>
                <input type="radio" name="booking-mode" value="auto" checked={auto} onChange={() => switchMode("auto")} />
                <span>
                  <strong>Automatic token</strong>
                  <small>Next available time</small>
                </span>
              </label>
              <label className={!auto ? "booking-mode-option selected" : "booking-mode-option"}>
                <input type="radio" name="booking-mode" value="custom" checked={!auto} onChange={() => switchMode("custom")} />
                <span>
                  <strong>Choose custom time</strong>
                  <small>Pick from the free times</small>
                </span>
              </label>
            </div>
          )}
          {takenNotice && (
            <div role="status">
              <Alert kind="warn">{takenNotice}</Alert>
            </div>
          )}
          {error ? null : loading ? (
            <p className="muted small" role="status">
              Loading available times…
            </p>
          ) : fifo ? (
            <TokenRequest doctorId={doctorId} today={today} lastDay={current.bookable_until} />
          ) : emptyMonth ? (
            emptyMonthMessage
          ) : auto ? (
            date ? (
              <AutoTokenPanel
                doctorId={doctorId}
                date={date}
                patientId={patientId}
                selected={selected}
                onSelect={onSelect}
                onPickDate={pickDate}
                refreshKey={`${attempt}:${refreshKey}`}
              />
            ) : (
              <p className="muted">Select a date to get the next available time.</p>
            )
          ) : board.length === 0 ? (
            <p className="muted">No appointment times are available for this date.</p>
          ) : (
            <>
            {hours.length > 1 && (
              <div className="hour-grid" role="group" aria-label="Hour">
                {hours.map((h) => (
                  <button
                    type="button"
                    key={h}
                    className={h === hour ? "hour-chip selected" : "hour-chip"}
                    aria-pressed={h === hour}
                    aria-label={`${hourLabel(h)}, ${freeIn(h) === 0 ? "no free times" : `${freeIn(h)} free`}`}
                    disabled={freeIn(h) === 0}
                    onClick={() => setPickedHour(h)}
                  >
                    {hourLabel(h)}
                    <small>{freeIn(h) === 0 ? "Full" : `${freeIn(h)} free`}</small>
                  </button>
                ))}
              </div>
            )}
            <div className="time-grid" role="group" aria-label={`Times on ${longDate(date)}`}>
              {board.filter((s) => hourOf(s) === hour).map((s) =>
                s.free ? (
                  <button
                    type="button"
                    key={s.starts_at}
                    className={s.starts_at === slot?.starts_at ? "time-slot selected" : "time-slot"}
                    aria-pressed={s.starts_at === slot?.starts_at}
                    onClick={() => choose(s)}
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                ) : (
                  <button
                    type="button"
                    key={s.starts_at}
                    className="time-slot"
                    disabled
                    aria-label={`${formatSlotTime(s.starts_at, timezone)}, unavailable`}
                    title="Not available"
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                )
              )}
            </div>
            {current?.consultation_minutes && <p className="muted small">{current.consultation_minutes}-minute appointments.</p>}
            </>
          )}
          {timezone && !fifo && (
            <p className="timezone-note">
              <Info size={18} aria-hidden="true" />
              <span>
                Selected time zone: {timeZoneLabel(timezone, slot?.starts_at ?? `${date ?? today}T12:00:00Z`)}
                <span className="muted small"> · clinic time</span>
              </span>
            </p>
          )}
        </section>
      </div>
    );
  }

  if (error) return retry;

  return (
    <>
      {calendar}

      <div className="booking-times">
        <h3>
          <Clock size={18} aria-hidden="true" /> Available times
        </h3>
        {takenNotice && (
          <div role="status">
            <Alert kind="warn">{takenNotice}</Alert>
          </div>
        )}
        {loading ? (
          <p className="muted small" role="status">
            Loading available times…
          </p>
        ) : emptyMonth ? (
          emptyMonthMessage
        ) : slots.length === 0 ? (
          <p className="muted">No appointment times are available for this date.</p>
        ) : (
          <>
            <p className="muted small">{longDate(date)}</p>
            <div className="slot-grid" role="group" aria-label={`Available times on ${longDate(date)}`}>
              {board.map((s) =>
                s.free ? (
                  <button
                    type="button"
                    key={s.starts_at}
                    className={s.starts_at === slot?.starts_at ? "selected" : "secondary"}
                    aria-pressed={s.starts_at === slot?.starts_at}
                    onClick={() => choose(s)}
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                ) : (
                  <button
                    type="button"
                    key={s.starts_at}
                    className="secondary unavailable"
                    disabled
                    aria-label={`${formatSlotTime(s.starts_at, timezone)}, unavailable`}
                    title="Not available"
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                )
              )}
            </div>
            <p className="muted small">Times are in the clinic's time zone ({timezone}).</p>
          </>
        )}
      </div>
    </>
  );
}
