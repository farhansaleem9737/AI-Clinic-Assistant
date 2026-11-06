import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getNotificationPreferences,
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  updateNotificationPreferences,
} from "../../services/workspaceService";
import NotificationBell from "./NotificationBell";

vi.mock("../../services/workspaceService");

const APPT = "01a0ed6e-7dcf-7b64-bc44-8d7e5496d463";
const note = (id, extra = {}) => ({
  id, type: "appointment_reminder", title: `Note ${id}`, message: "Your appointment is soon.", link: `/appointments/${APPT}`,
  read_at: null, created_at: "2027-04-23T05:00:00Z", ...extra,
});
let visibility = "visible";

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}
function renderBell() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <NotificationBell />
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}
const openPanel = async () => {
  await userEvent.click(screen.getByRole("button", { name: /Notifications/ }));
  return screen.getByRole("dialog", { name: "Notifications" });
};

beforeEach(() => {
  vi.resetAllMocks();
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  getUnreadCount.mockResolvedValue({ data: { unread: 1 } });
  listNotifications.mockResolvedValue({ data: { items: [note("n-1")], unread: 1, has_more: false } });
  markNotificationRead.mockResolvedValue({ data: {} });
  markAllNotificationsRead.mockResolvedValue({ data: { unread: 0 } });
});
afterEach(() => vi.useRealTimers());

describe("notification center", () => {
  it("refreshes the count only while the tab is visible, and when the user comes back", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderBell();
    await waitFor(() => expect(getUnreadCount).toHaveBeenCalledTimes(1));
    visibility = "hidden";
    await act(async () => vi.advanceTimersByTime(130_000));
    expect(getUnreadCount).toHaveBeenCalledTimes(1); // no polling from a hidden tab
    visibility = "visible";
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(getUnreadCount).toHaveBeenCalledTimes(2);
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(getUnreadCount).toHaveBeenCalledTimes(2); // not again within 15 s
    await act(async () => vi.advanceTimersByTime(120_000));
    expect(getUnreadCount).toHaveBeenCalledTimes(3);
  });

  it("opens a notification's page, marks it read, and pages back through older ones", async () => {
    listNotifications
      .mockResolvedValueOnce({ data: { items: [note("n-1"), note("n-2", { read_at: "2027-04-23T06:00:00Z" })], unread: 1, has_more: true } })
      .mockResolvedValueOnce({ data: { items: [note("n-3", { read_at: "2027-04-22T06:00:00Z" })], unread: 1, has_more: false } });
    renderBell();
    const panel = await openPanel();
    const first = await within(panel).findByRole("button", { name: /Note n-1/ });
    expect(first).toHaveClass("unread");
    expect(within(panel).getByRole("button", { name: /Note n-2/ })).not.toHaveClass("unread");
    await userEvent.click(within(panel).getByRole("button", { name: "Show older notifications" }));
    expect(await within(panel).findByRole("button", { name: /Note n-3/ })).toBeInTheDocument();
    expect(listNotifications).toHaveBeenLastCalledWith(15, 2);
    expect(within(panel).queryByRole("button", { name: "Show older notifications" })).not.toBeInTheDocument();
    await userEvent.click(first);
    expect(markNotificationRead).toHaveBeenCalledWith("n-1");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`/appointments/${APPT}`));
  });

  it("never follows a link that is not a page of this app", async () => {
    listNotifications.mockResolvedValue({ data: { items: [note("n-1", { link: "https://evil.example/phish" })], unread: 1 } });
    renderBell();
    const panel = await openPanel();
    await userEvent.click(await within(panel).findByRole("button", { name: /Note n-1/ }));
    expect(markNotificationRead).toHaveBeenCalledWith("n-1");
    expect(screen.getByTestId("where")).toHaveTextContent("/dashboard");
  });

  it("explains a loading failure and can try again; Escape closes and returns focus", async () => {
    listNotifications.mockRejectedValueOnce({ response: { status: 503, data: { error: { message: "Service unavailable" } } } });
    renderBell();
    const panel = await openPanel();
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Service unavailable");
    await userEvent.click(within(panel).getByRole("button", { name: "Try again" }));
    expect(await within(panel).findByRole("button", { name: /Note n-1/ })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Notifications" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Notifications/ })).toHaveFocus();
  });

  it("marks all as read", async () => {
    renderBell();
    const panel = await openPanel();
    await within(panel).findByRole("button", { name: /Note n-1/ });
    await userEvent.click(within(panel).getByRole("button", { name: "Mark all as read" }));
    expect(markAllNotificationsRead).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument(); // no unread left
  });

  it("switches optional categories off, and puts the switch back if saving fails", async () => {
    getNotificationPreferences.mockResolvedValue({ data: { appointment_updates: true, reminders: true, follow_ups: true, emails: true } });
    updateNotificationPreferences.mockResolvedValueOnce({ data: { appointment_updates: true, reminders: false, follow_ups: true, emails: true } });
    updateNotificationPreferences.mockRejectedValueOnce({ response: { status: 500, data: {} } });
    renderBell();
    const panel = await openPanel();
    await userEvent.click(within(panel).getByRole("button", { name: "Notification settings" }));
    const reminders = await within(panel).findByRole("checkbox", { name: /Appointment reminders/ });
    await waitFor(() => expect(reminders).toBeChecked());
    await userEvent.click(reminders);
    expect(updateNotificationPreferences).toHaveBeenCalledWith({ reminders: false });
    await waitFor(() => expect(reminders).not.toBeChecked());
    const followUps = within(panel).getByRole("checkbox", { name: /Follow-up reminders/ });
    await userEvent.click(followUps);
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Could not save your notification settings");
    expect(followUps).toBeChecked();
    expect(within(panel).getByText(/Essential notifications/)).toBeInTheDocument();
    expect(within(panel).getByRole("checkbox", { name: /Also by email/ })).toBeChecked();
  });

  it("turns every optional notification off at once, and back on", async () => {
    const off = { appointment_updates: false, reminders: false, follow_ups: false, emails: false };
    const on = { appointment_updates: true, reminders: true, follow_ups: true, emails: true };
    getNotificationPreferences.mockResolvedValue({ data: on });
    updateNotificationPreferences.mockResolvedValueOnce({ data: off }).mockResolvedValueOnce({ data: on });
    renderBell();
    const panel = await openPanel();
    await userEvent.click(within(panel).getByRole("button", { name: "Notification settings" }));
    const all = await within(panel).findByRole("checkbox", { name: /Turn off all notifications/ });
    await waitFor(() => expect(within(panel).getByRole("checkbox", { name: /Appointment reminders/ })).toBeChecked());
    expect(all).not.toBeChecked();
    await userEvent.click(all);
    expect(updateNotificationPreferences).toHaveBeenLastCalledWith(off);
    await waitFor(() => expect(all).toBeChecked());
    expect(within(panel).getByRole("checkbox", { name: /Appointment reminders/ })).not.toBeChecked();
    await userEvent.click(all);
    expect(updateNotificationPreferences).toHaveBeenLastCalledWith(on);
    await waitFor(() => expect(within(panel).getByRole("checkbox", { name: /Also by email/ })).toBeChecked());
  });
});
