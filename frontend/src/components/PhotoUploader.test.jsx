import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PhotoUploader from "./PhotoUploader";

const fileInput = (container) => container.querySelector('input[type="file"]');

describe("PhotoUploader", () => {
  it("refuses a non-image without calling the API", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const onUpload = vi.fn();
    const { container } = render(<PhotoUploader name="Ada Lovelace" onUpload={onUpload} />);
    await user.upload(fileInput(container), new File(["<svg/>"], "x.svg", { type: "image/svg+xml" }));
    expect(onUpload).not.toHaveBeenCalled();
    expect(screen.getByText(/JPEG, PNG or WebP image/)).toBeInTheDocument();
  });

  it("passes a valid image to onUpload", async () => {
    const user = userEvent.setup();
    const onUpload = vi.fn().mockResolvedValue();
    const { container } = render(<PhotoUploader name="Ada Lovelace" onUpload={onUpload} />);
    const png = new File([new Uint8Array([137, 80, 78, 71])], "me.png", { type: "image/png" });
    await user.upload(fileInput(container), png);
    expect(onUpload).toHaveBeenCalledWith(png);
  });

  it("shows the API's error message", async () => {
    const user = userEvent.setup();
    const onUpload = vi.fn().mockRejectedValue({
      response: { data: { error: { code: "UNSUPPORTED_FILE", message: "The image could not be read" } } },
    });
    const { container } = render(<PhotoUploader name="Ada Lovelace" onUpload={onUpload} />);
    await user.upload(fileInput(container), new File(["x"], "me.png", { type: "image/png" }));
    expect(await screen.findByText("The image could not be read")).toBeInTheDocument();
  });

  it("offers Remove only when there is a photo", () => {
    const { rerender } = render(<PhotoUploader name="Ada Lovelace" onUpload={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    rerender(
      <PhotoUploader name="Ada Lovelace" photoUrl="https://example.test/p.webp" onUpload={vi.fn()} onRemove={vi.fn()} />
    );
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });
});
