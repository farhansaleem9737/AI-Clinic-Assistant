import { describe, expect, it } from "vitest";
import { appointment } from "../test/fixtures";
import { appointmentIcs, appointmentLocation, canAddToCalendar } from "./ics";

const NOW = new Date("2026-10-01T08:00:00Z");

describe("appointmentIcs", () => {
  it("describes the appointment as one UTC-timed event", () => {
    const ics = appointmentIcs(appointment({ reason: "Chest pain" }), NOW);
    const lines = ics.split("\r\n");
    expect(lines[0]).toBe("BEGIN:VCALENDAR");
    expect(lines).toContain("VERSION:2.0");
    expect(lines).toContain("UID:appt-1@clinic-ai-assistant");
    expect(lines).toContain("DTSTAMP:20261001T080000Z");
    expect(lines).toContain("DTSTART:20261005T050000Z");
    expect(lines).toContain("DTEND:20261005T053000Z");
    expect(lines).toContain("SUMMARY:Appointment with Dr. Sarah Khan");
    expect(lines).toContain("LOCATION:Room B-12\\, Cardiology");
    expect(lines).toContain("STATUS:CONFIRMED");
    expect(ics.endsWith("END:VCALENDAR\r\n")).toBe(true);
  });

  it("keeps the reason for the visit out of the calendar", () => {
    expect(appointmentIcs(appointment({ reason: "Chest pain" }), NOW)).not.toContain("Chest pain");
  });

  it("escapes text and folds long lines", () => {
    const doctor = { ...appointment().doctor, specialization: "Cardiology; heart, vessels and more ".repeat(4) };
    const ics = appointmentIcs(appointment({ status: "scheduled", doctor }), NOW);
    expect(ics).toContain("\\;");
    expect(ics).toContain("STATUS:TENTATIVE");
    for (const line of ics.split("\r\n")) expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75);
    // Unfolding restores the original line.
    expect(ics.replace(/\r\n /g, "")).toContain("DESCRIPTION:Cardiology\\; heart\\, vessels");
  });

  it("leaves out a location the appointment does not have", () => {
    const doctor = { ...appointment().doctor, room_number: null };
    expect(appointmentLocation(appointment({ doctor }))).toBe("Cardiology");
  });
});

describe("canAddToCalendar", () => {
  it.each([
    ["confirmed", "2026-10-05T05:30:00Z", true],
    ["scheduled", "2026-10-05T05:30:00Z", true],
    ["cancelled", "2026-10-05T05:30:00Z", false],
    ["completed", "2026-10-05T05:30:00Z", false],
    ["confirmed", "2026-09-30T05:30:00Z", false], // already over
  ])("%s ending %s → %s", (status, ends_at, expected) => {
    expect(canAddToCalendar(appointment({ status, ends_at }), NOW)).toBe(expected);
  });
});
