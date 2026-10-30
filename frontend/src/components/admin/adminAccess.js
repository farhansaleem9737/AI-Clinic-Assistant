// Labels for the administrator-access section (D87).

export const INVITATION_STATUS = {
  pending: { label: "Pending", tone: "info" },
  accepted: { label: "Accepted", tone: "ok" },
  revoked: { label: "Revoked", tone: "danger" },
  expired: { label: "Expired", tone: "warn" },
};

// What the email provider said: never claim "sent" unless it accepted the message.
export const DELIVERY = {
  sent: "Email sent",
  outbox: "Saved to development outbox",
  failed: "Email failed",
  not_configured: "Email not configured",
};

export const deliveryLabel = (status) => DELIVERY[status] ?? "Not sent";

export function inviteNotice(invitation) {
  switch (invitation.delivery_status) {
    case "sent":
      return `Invitation sent to ${invitation.email}.`;
    case "outbox":
      return `Invitation created for ${invitation.email}. Development mode: the email was saved to backend/var/outbox instead of being sent.`;
    default:
      return `Invitation created for ${invitation.email}, but the email could not be sent (${deliveryLabel(invitation.delivery_status).toLowerCase()}). Fix email delivery, then use Resend.`;
  }
}

export const formatDateTime = (iso) =>
  iso ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso)) : "—";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateInvite(form) {
  const errors = {};
  if (!form.email.trim()) errors.email = "Enter an email address.";
  else if (!EMAIL.test(form.email.trim())) errors.email = "Enter a valid email address.";
  if (form.name.length > 100) errors.name = "Use at most 100 characters.";
  if (!form.current_password) errors.current_password = "Enter your password to confirm.";
  return errors;
}
