import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import CareerEditor from "./CareerEditor";

const career = {
  experience: [
    { title: "Senior Cardiologist", organization: "City General", location: "Lahore", start_year: 2020, end_year: null, description: null },
  ],
  education: [{ qualification: "MBBS", institution: "KEMU", field_of_study: null, start_year: null, end_year: 2011 }],
};

function renderEditor(save = vi.fn()) {
  const load = vi.fn().mockResolvedValue({ data: career });
  render(<CareerEditor load={load} save={save} />);
  return { load, save };
}

describe("CareerEditor", () => {
  it("shows the stored history ready to edit", async () => {
    renderEditor();
    const position = await screen.findByRole("group", { name: "Position 1" });
    expect(within(position).getByLabelText("Job title")).toHaveValue("Senior Cardiologist");
    expect(within(position).getByLabelText("To")).toHaveValue(null); // blank = current position
    expect(within(screen.getByRole("group", { name: "Qualification 1" })).getByLabelText("Institution")).toHaveValue("KEMU");
  });

  it("adds, removes and saves, sending clean values", async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue({ data: { experience: [], education: [] } });
    renderEditor(save);
    await screen.findByRole("group", { name: "Position 1" });

    await user.click(screen.getByRole("button", { name: /Add position/ }));
    const added = screen.getByRole("group", { name: "Position 2" });
    await user.type(within(added).getByLabelText("Job title"), "  Consultant ");
    await user.type(within(added).getByLabelText("Hospital or organization"), "Heart Centre");
    await user.type(within(added).getByLabelText("From"), "2016");
    await user.type(within(added).getByLabelText("To"), "2020");
    await user.click(within(screen.getByRole("group", { name: "Qualification 1" })).getByRole("button", { name: /Remove/ }));
    await user.click(screen.getByRole("button", { name: "Save career history" }));

    expect(save).toHaveBeenCalledWith({
      experience: [
        { title: "Senior Cardiologist", organization: "City General", location: "Lahore", start_year: 2020, end_year: null, description: null },
        { title: "Consultant", organization: "Heart Centre", location: null, start_year: 2016, end_year: 2020, description: null },
      ],
      education: [],
    });
    expect(await screen.findByText("Career history saved")).toBeInTheDocument();
  });

  it("shows the server's validation message", async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockRejectedValue({
      response: { data: { error: { code: "VALIDATION_ERROR", message: "x", details: { errors: [{ loc: ["body", "experience", 0, "end_year"], msg: "end_year must not be before start_year" }] } } } },
    });
    renderEditor(save);
    await screen.findByRole("group", { name: "Position 1" });
    await user.click(screen.getByRole("button", { name: "Save career history" }));
    expect(await screen.findByText(/end_year must not be before start_year/)).toBeInTheDocument();
  });
});
