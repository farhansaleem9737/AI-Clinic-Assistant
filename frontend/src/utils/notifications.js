// Where a notification may lead: pages of this app only. The server keeps the
// same list (notification_service.safe_link); anything else opens nothing.
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const SAFE_LINK = new RegExp(
  `^/(dashboard|appointments|appointments/${UUID}|appointments/book([?]doctor=${UUID})?|schedule|doctor/profile|doctor/application|profile|admin/doctors|admin/users)$`
);

export const safeLink = (link) => (typeof link === "string" && SAFE_LINK.test(link) ? link : null);
