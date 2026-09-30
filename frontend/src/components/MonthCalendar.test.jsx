import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { addMonths, monthBounds, monthGrid } from "../utils/calendar";
import MonthCalendar from "./MonthCalendar";

describe("calendar arithmetic", () => {
  it("moves across year boundaries", () => {
    expect(addMonths("2026-12", 1)).toBe("2027-01");
    expect(addMonths("2026-01", -1)).toBe("2025-12");
  });

  it("knows the last day of the month, including leap years", () => {
    expect(monthBounds("2026-02")).toEqual({ first: "2026-02-01", last: "2026-02-28" });
    expect(monthBounds("2028-02").last).toBe("2028-02-29");
  });

  it("builds whole weeks starting on Sunday", () => {
    const april = monthGrid("2026-04"); // 1 April 2026 is a Wednesday
    expect(april.length % 7).toBe(0);
    expect(april[0]).toEqual({ date: "2026-03-29", inMonth: false });
    expect(april[3]).toEqual({ date: "2026-04-01", inMonth: true });
    expect(april.filter((d) => d.inMonth)).toHaveLength(30);
  });
});

describe("MonthCalendar", () => {
  const props = { month: "2026-04", today: "2026-04-23", onMonthChange: vi.fn(), onSelectDay: vi.fn() };

  it("marks days with appointments and makes only those clickable", async () => {
    render(<MonthCalendar {...props} marks={{ "2026-04-25": "ok", "2026-04-28": "warn" }} />);
    const marked = screen.getAllByRole("button", { name: /has appointments/ });
    expect(marked).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "2026-04-25, has appointments" }));
    expect(props.onSelectDay).toHaveBeenCalledWith("2026-04-25");
  });

  it("highlights today and navigates between months", async () => {
    render(<MonthCalendar {...props} />);
    expect(screen.getByText("23")).toHaveClass("today");
    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(props.onMonthChange).toHaveBeenCalledWith("2026-05");
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(props.onMonthChange).toHaveBeenCalledWith("2026-03");
  });
});
