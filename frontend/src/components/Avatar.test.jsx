import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Avatar from "./Avatar";

const kind = (container) => container.firstChild.dataset.avatar ?? container.firstChild.tagName.toLowerCase();

describe("Avatar fallbacks", () => {
  it("case 1: a doctor without a picture gets the illustrated doctor", () => {
    const { container } = render(<Avatar name="Sarah Khan" role="doctor" />);
    expect(kind(container)).toBe("doctor");
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("case 2: a doctor's uploaded picture is shown instead", () => {
    const { container } = render(<Avatar name="Sarah Khan" role="doctor" src="/media/sarah.jpg" alt="Dr. Sarah Khan" />);
    const img = screen.getByRole("img", { name: "Dr. Sarah Khan" });
    expect(img.tagName).toBe("IMG");
    expect(img).toHaveAttribute("src", "/media/sarah.jpg");
    expect(container.querySelector("svg")).toBeNull();
  });

  it("case 3: a patient without a picture gets their initials", () => {
    const { container } = render(<Avatar name="John Doe" />);
    expect(kind(container)).toBe("initials");
    expect(container.firstChild).toHaveTextContent("JD");
  });

  it("case 4: a patient's uploaded picture is shown instead", () => {
    render(<Avatar name="John Doe" src="/media/john.png" alt="John Doe" />);
    expect(screen.getByRole("img", { name: "John Doe" })).toHaveAttribute("src", "/media/john.png");
  });

  it("case 5: a picture that fails to load falls back, never a broken image", () => {
    const { container, rerender } = render(<Avatar name="Sarah Khan" role="doctor" src="/media/missing.jpg" />);
    fireEvent.error(container.querySelector("img"));
    expect(kind(container)).toBe("doctor");
    expect(container.querySelector("img")).toBeNull();

    // A new picture is tried again.
    rerender(<Avatar name="Sarah Khan" role="doctor" src="/media/new.jpg" />);
    expect(container.querySelector("img")).toHaveAttribute("src", "/media/new.jpg");

    const patient = render(<Avatar name="John Doe" src="/media/missing.jpg" />);
    fireEvent.error(patient.container.querySelector("img"));
    expect(kind(patient.container)).toBe("initials");
  });

  it("ignores titles when making initials and copes with an empty name", () => {
    const { container } = render(<Avatar name="Dr. Sarah Khan" />);
    expect(container.firstChild).toHaveTextContent("SK");
    const empty = render(<Avatar />);
    expect(empty.container.firstChild).toHaveTextContent("?");
  });

  it("is decorative unless given alt text", () => {
    const { container } = render(<Avatar name="John Doe" />);
    expect(container.firstChild).toHaveAttribute("aria-hidden", "true");
    render(<Avatar name="Sarah Khan" role="doctor" alt="Dr. Sarah Khan" />);
    expect(screen.getByRole("img", { name: "Dr. Sarah Khan" })).toBeInTheDocument();
  });
});
