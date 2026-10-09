// Optional clinic contact details, set per deployment (frontend .env). When
// they are not set, pages point people to reception instead of inventing
// a number.
export const SUPPORT_PHONE = import.meta.env.VITE_SUPPORT_PHONE?.trim() || "";
export const SUPPORT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL?.trim() || "";

export const telHref = (phone) => `tel:${phone.replace(/[^\d+]/g, "")}`;
