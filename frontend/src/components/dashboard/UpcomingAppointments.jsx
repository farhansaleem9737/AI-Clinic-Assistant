import { CalendarClock, CalendarDays, CalendarPlus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { changeAppointmentStatus, listAppointments } from "../../services/appointmentService";
import { formatDateTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import ConfirmDialog from "../ConfirmDialog";
import SectionCard from "../SectionCard";
import AppointmentList from "./AppointmentList";

const PREVIEW_SIZE = 3;

function Panel({ icon: Icon, title, children, action }) {
  return (
    <div className="upcoming-panel">
      <span className="upcoming-panel-icon">
        <Icon size={20} aria-hidden="true" />
      </span>
      <div>
        <strong>{title}</strong>
        <p className="muted small">{children}</p>
      </div>
      {action}
    </div>
  );
}

/**
 * The patient's next appointments (D98). The card fills its row and its
 * content adapts to how many there are, so a short list never leaves a blank
 * block: none shows a centred invitation to book; one adds the "Need to make
 * changes?" and "Planning another visit?" panels; two or three sit above the
 * changes panel; more than three show the nearest three and say how many
 * there are in all. Every row is a real appointment from the API.
 */
export default function UpcomingAppointments({ enabled, onChanged }) {
  const [attempt, setAttempt] = useState(0);
  const [cancelling, setCancelling] = useState(null); // { appointment, note, busy, error }
  const { data, loading, error } = useFetch(() => listAppointments({ scope: "upcoming", page_size: PREVIEW_SIZE }), [attempt], {
    enabled,
  });
  const items = [...(data?.items ?? [])].sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at));
  const total = Math.max(data?.total ?? items.length, items.length);

  const menu = (a) =>
    [
      { label: "View details", to: `/appointments/${a.id}` },
      a.can_reschedule && { label: "Reschedule", to: `/appointments/${a.id}?reschedule=1` },
      a.allowed_transitions?.includes("cancelled") && {
        label: "Cancel appointment",
        danger: true,
        onSelect: () => setCancelling({ appointment: a, note: "", busy: false, error: "" }),
      },
    ].filter(Boolean);

  const cancel = async () => {
    setCancelling((c) => ({ ...c, busy: true, error: "" }));
    try {
      await changeAppointmentStatus(cancelling.appointment.id, {
        status: "cancelled",
        cancellation_reason: "patient_request",
        note: cancelling.note.trim() || null,
      });
      setCancelling(null);
      setAttempt((n) => n + 1);
      onChanged?.();
    } catch (err) {
      setCancelling((c) => ({ ...c, busy: false, error: getErrorMessage(err, "Could not cancel the appointment") }));
    }
  };

  return (
    <SectionCard
      title="Upcoming Appointments"
      icon={CalendarDays}
      moreTo="/appointments"
      loading={loading && !data}
      error={error}
      onRetry={() => setAttempt((n) => n + 1)}
      className={`upcoming-card count-${Math.min(items.length, 4)}`}
    >
      {items.length === 0 ? (
        <div className="upcoming-empty">
          <span className="upcoming-empty-art" aria-hidden="true">
            <CalendarPlus size={40} />
          </span>
          <h4>No upcoming appointments.</h4>
          <p className="muted">When you book a visit it will appear here, with the doctor, time and status.</p>
          <Link to="/doctors" className="button">
            <Search size={16} aria-hidden="true" /> Find a doctor
          </Link>
        </div>
      ) : (
        <>
          <AppointmentList appointments={items} menu={menu} density={items.length >= 3 ? "compact" : "comfortable"} />
          {total > items.length && (
            <p className="upcoming-more muted small">
              Showing the next {items.length} of {total} upcoming appointments.{" "}
              <Link to="/appointments">View all</Link>
            </p>
          )}
          <div className="upcoming-panels">
            <Panel
              icon={CalendarClock}
              title="Need to make changes?"
              action={
                <Link to="/appointments" className="button secondary small">
                  Manage Appointments
                </Link>
              }
            >
              You can reschedule or cancel your appointment anytime, subject to clinic policy.
            </Panel>
            {items.length === 1 && (
              <Panel
                icon={Search}
                title="Planning another visit?"
                action={
                  <Link to="/doctors" className="button small">
                    Find a Doctor
                  </Link>
                }
              >
                Explore available doctors and book your next appointment.
              </Panel>
            )}
          </div>
        </>
      )}

      {cancelling && (
        <ConfirmDialog
          title="Cancel this appointment?"
          confirmLabel="Cancel appointment"
          cancelLabel="Keep appointment"
          danger
          busy={cancelling.busy}
          error={cancelling.error}
          onConfirm={cancel}
          onCancel={() => setCancelling(null)}
        >
          <p>
            {doctorName(cancelling.appointment.doctor)} on{" "}
            <strong>{formatDateTime(cancelling.appointment.starts_at, cancelling.appointment.timezone)}</strong>. The time
            will be released for other patients.
          </p>
          <label>
            Note for the clinic (optional)
            <textarea
              value={cancelling.note}
              maxLength={500}
              onChange={(e) => setCancelling((c) => ({ ...c, note: e.target.value }))}
            />
          </label>
        </ConfirmDialog>
      )}
    </SectionCard>
  );
}
