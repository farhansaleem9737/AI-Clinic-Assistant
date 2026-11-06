import { describe, expect, it } from "vitest";
import { formatAddress } from "./locations";
import { joinPhone, nationalIdError, phoneError, splitPhone } from "./profileForms";

describe("profile form rules (D111)", () => {
  it("CNIC for Pakistan; another country's ID only for its characters", () => {
    expect(nationalIdError("34101-1234567-1", "PK")).toBe("");
    expect(nationalIdError("3410112345671", null)).toBe("");
    expect(nationalIdError("34101-123456", "PK")).toMatch(/13-digit CNIC/);
    expect(nationalIdError("12345", null)).toMatch(/13-digit CNIC/);
    expect(nationalIdError("AB 12 34 56 C", "GB")).toBe("");
    expect(nationalIdError("<script>", "GB")).toMatch(/letters, digits/);
  });

  it("splits and joins phone numbers without rewriting saved ones", () => {
    expect(splitPhone("+92 3001234567", "PK")).toEqual({ dial: "92", number: "3001234567" });
    expect(splitPhone("+923001234567", "PK")).toEqual({ dial: "92", number: "3001234567" });
    expect(splitPhone("+971 501234567", "PK")).toEqual({ dial: "971", number: "501234567" });
    expect(splitPhone("00001111111", "PK")).toEqual({ dial: "92", number: "00001111111" }); // shown as saved
    expect(joinPhone("92", "0300-1234567")).toBe("+92 3001234567");
    expect(joinPhone("92", "+44 20 7946 0958")).toBe("+44 20 7946 0958"); // already international: kept
    expect(phoneError("92", "3001234567")).toBe("");
    expect(phoneError("92", "30012")).toMatch(/10 digits/);
    expect(phoneError("44", "abc")).toMatch(/digits only/);
  });

  it("formats the address from its saved parts", () => {
    expect(formatAddress({ address: "House 5", city: "Lahore", province: "Punjab", country: "PK" })).toBe("House 5, Lahore, Punjab, Pakistan");
    expect(formatAddress({ address: null, city: "Dubai", province: null, country: "AE" })).toBe("Dubai, United Arab Emirates");
  });
});
