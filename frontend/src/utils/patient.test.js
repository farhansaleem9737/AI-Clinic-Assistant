import { describe, expect, it } from "vitest";
import { ageFromDateOfBirth, patientFullName } from "./patient";

// Midday, so the test means the same calendar day in every time zone.
const on = (isoDate) => new Date(`${isoDate}T12:00:00`);

describe("ageFromDateOfBirth", () => {
  it("counts whole years", () => {
    expect(ageFromDateOfBirth("1990-01-01", on("2026-10-26"))).toBe(36);
  });

  it("is one year less on the day before the birthday", () => {
    expect(ageFromDateOfBirth("1990-10-27", on("2026-10-26"))).toBe(35);
  });

  it("goes up on the birthday itself", () => {
    expect(ageFromDateOfBirth("1990-10-26", on("2026-10-26"))).toBe(36);
  });

  it("returns null when there is no date or it is in the future", () => {
    expect(ageFromDateOfBirth(null)).toBeNull();
    expect(ageFromDateOfBirth("2030-01-01", on("2026-10-26"))).toBeNull();
  });
});

describe("patientFullName", () => {
  it("joins first and last name", () => {
    expect(patientFullName({ first_name: "Ada", last_name: "Lovelace" })).toBe("Ada Lovelace");
  });

  it("copes with missing parts", () => {
    expect(patientFullName({ first_name: "Ada" })).toBe("Ada");
    expect(patientFullName(null)).toBe("");
  });
});
