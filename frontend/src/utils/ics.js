// "Add to calendar": an iCalendar (.ics) file for one appointment, built in
// the browser from the appointment the API returned (RFC 5545).
//
// Times are written as UTC instants, which every calendar app converts to the
// viewer's own timezone. The event carries the doctor and the room only: the
// reason for the visit stays out, because calendars are often shared or synced.

import { ACTIVE_STATUSES } from "./appointments";
import { isoDateIn } from "./datetime";
import { doctorName } from "./format";

const CRLF = "\r\n";

// 2026-10-07T05:00:00.000Z -> 20261007T050000Z
const utcStamp = (value) => new Date(value).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

function escapeText(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

// Content lines longer than 75 octets are folded: CRLF + one space, never
// splitting a multi-byte character.
function fold(line) {
  const encoder = new TextEncoder();
  const parts = [];
  let current = "";
  let size = 0;
  for (const char of line) {
    const bytes = encoder.encode(char).length;
    const limit = parts.length === 0 ? 75 : 74; // continuation lines start with a space
    if (size + bytes > limit) {
      parts.push(current);
      current = "";
      size = 0;
    }
    current += char;
    size += bytes;
  }
  parts.push(current);
  return parts.join(`${CRLF} `);
}

export function appointmentLocation(appointment) {
  const { room_number: room, department_name: department } = appointment.doctor;
  return [room && `Room ${room}`, department].filter(Boolean).join(", ");
}

export function appointmentIcs(appointment, now = new Date()) {
  const doctor = appointment.doctor;
  const location = appointmentLocation(appointment);
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Clinic AI Assistant//Appointments//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${appointment.id}@clinic-ai-assistant`,
    `DTSTAMP:${utcStamp(now)}`,
    `DTSTART:${utcStamp(appointment.starts_at)}`,
    `DTEND:${utcStamp(appointment.ends_at)}`,
    `SUMMARY:${escapeText(`Appointment with ${doctorName(doctor)}`)}`,
    location && `LOCATION:${escapeText(location)}`,
    `DESCRIPTION:${escapeText(`${doctor.specialization}, ${doctor.department_name}. Clinic time zone: ${appointment.timezone}.`)}`,
    `STATUS:${appointment.status === "confirmed" ? "CONFIRMED" : "TENTATIVE"}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].filter(Boolean);
  return lines.map(fold).join(CRLF) + CRLF;
}

// Only appointments that are still going ahead belong in a calendar.
export function canAddToCalendar(appointment, now = new Date()) {
  return ACTIVE_STATUSES.includes(appointment.status) && new Date(appointment.ends_at) > now;
}

export function downloadAppointmentIcs(appointment) {
  const blob = new Blob([appointmentIcs(appointment)], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `appointment-${isoDateIn(appointment.starts_at, appointment.timezone)}.ics`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
