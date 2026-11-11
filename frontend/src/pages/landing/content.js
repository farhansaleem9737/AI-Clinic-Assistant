// Everything the public landing page says, in one place. Every statement here
// describes what the application actually does today (see docs/ARCHITECTURE.md
// and docs/AI_ASSISTANT.md); keep it that way when the product changes.
import {
  Building2,
  CalendarCheck,
  ClipboardList,
  FileText,
  HardDrive,
  KeyRound,
  LayoutDashboard,
  Lock,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  UserCog,
  Users,
} from "lucide-react";

export const NAV_SECTIONS = [
  { id: "home", label: "Home" },
  { id: "features", label: "Features" },
  { id: "architecture", label: "Architecture" },
  { id: "security", label: "Security" },
  { id: "pricing", label: "Pricing" },
];

export const FEATURES = [
  {
    icon: CalendarCheck,
    tone: "blue",
    title: "AI Appointment Assistant",
    text: "Ask in your own words; the assistant finds doctors and free slots from the clinic's live schedule.",
    points: [
      "Book, reschedule or cancel — always confirmed by you before anything changes",
      "Real availability checked again by the server at confirmation",
      "Review past and upcoming visits",
    ],
    link: { to: "/appointments/book", label: "Book an appointment" },
  },
  {
    icon: FileText,
    tone: "violet",
    title: "Medical Document Intelligence",
    text: "Keep reports on your record and get plain-language explanations of lab values — not a diagnosis.",
    points: [
      "PDF text and lab tables read on the clinic's own server",
      "Values compared only with the reference range printed on the report",
      "Unreadable, damaged or protected files are reported, never guessed",
    ],
    link: { to: "/profile", label: "Open my documents" },
  },
  {
    icon: Users,
    tone: "green",
    title: "Role-Based Clinic Workflows",
    text: "Patients, doctors, receptionists and administrators each get the tools their role needs — and nothing more.",
    points: ["One account system, four workspaces", "Permissions checked by the server on every request", "Doctors join through an approval process"],
    link: { href: "#showcase", label: "See each workspace" },
  },
  {
    icon: ShieldCheck,
    tone: "amber",
    title: "Security and Privacy",
    text: "Short-lived sessions, relationship-based access to records and an audit trail for sensitive changes.",
    points: ["Access tokens kept in memory, never in browser storage", "Records you have no link to return “not found”", "Private file storage behind access checks"],
    link: { href: "#security", label: "How we protect data" },
  },
  {
    icon: Stethoscope,
    tone: "cyan",
    title: "Doctor Discovery",
    text: "A public directory anyone can browse — no account needed to look around.",
    points: ["Search by name or specialty", "Filter by department", "Profiles with experience, fees and open slots"],
    link: { to: "/doctors", label: "Browse doctors" },
  },
  {
    icon: LayoutDashboard,
    tone: "navy",
    title: "Operational Dashboards",
    text: "Each role opens on a dashboard with the figures and lists that matter to it.",
    points: ["Today's appointments and recent activity", "User, doctor and department management for admins", "Schedules and check-in for the front desk"],
    link: { to: "/login", label: "Sign in to your dashboard" },
  },
];

export const ROLES = [
  { role: "Patient", icon: Users, items: ["Find doctors and book visits", "Manage personal details", "Review appointment history", "Keep medical documents on file"] },
  { role: "Doctor", icon: Stethoscope, items: ["Maintain a professional profile", "Set weekly availability and leave", "Review own appointments", "See patients they have visits with"] },
  { role: "Receptionist", icon: ClipboardList, items: ["Register and find patients", "Book for patients", "Coordinate doctor schedules", "Check patients in"] },
  { role: "Admin", icon: UserCog, items: ["Manage users and roles", "Manage departments and doctors", "Approve doctor applications", "Monitor clinic activity"] },
];

export const LIFECYCLES = [
  {
    id: "auth",
    title: "Signing in",
    steps: [
      "You sign in with email and password.",
      "The server checks your password against its bcrypt hash.",
      "You get a 15-minute access token (kept in memory) and a refresh token in an HttpOnly cookie.",
      "Each request is checked for the permission and for your relationship to the record.",
      "Only what your role may see is returned. Sessions renew quietly and end on sign-out.",
    ],
  },
  {
    id: "booking",
    title: "Booking an appointment",
    steps: [
      "Choose a doctor from the directory.",
      "Free slots are computed from the doctor's schedule and leave.",
      "Pick a time that suits you.",
      "The server validates the request and your permissions.",
      "The booking is saved; the database itself rejects any overlap.",
      "You see the confirmation and get a notification.",
    ],
  },
  {
    id: "ai",
    title: "Asking the assistant",
    steps: [
      "You send a message from the assistant panel.",
      "The server authenticates you and applies per-user and clinic-wide limits.",
      "Urgent symptoms get fixed emergency guidance with no model call.",
      "The model may call only the tools your role allows; data comes from the database.",
      "Gemini writes the reply from that permitted context.",
      "Changes like a booking come back as a proposal you confirm or cancel.",
      "On confirm, the server re-checks everything before it saves.",
    ],
  },
  {
    id: "documents",
    title: "Medical documents",
    steps: [
      "You choose a report to upload or open.",
      "The server checks your access and the file's type and size.",
      "The file is stored privately in object storage.",
      "Text and lab tables are extracted on the server.",
      "An explanation is prepared, within the clinic's AI privacy settings.",
      "Results are shown only to you and the doctors you have visits with.",
    ],
  },
];

export const SECURITY = [
  {
    icon: KeyRound,
    title: "Authentication and sessions",
    text: "Bcrypt password hashes, short-lived access tokens and rotating refresh tokens.",
    details: "Access tokens last 15 minutes and live only in memory. Refresh tokens are random, stored hashed, rotate on every use and expire after 14 days; presenting an old one revokes the whole session family. Signing out or changing your password ends your sessions.",
  },
  {
    icon: Users,
    title: "Role-based access control",
    text: "Two layers: what your role may do, and which records you are connected to.",
    details: "Permissions such as appointment:create are checked on every API request. A second check confirms your relationship to the specific record — a doctor sees only patients they have appointments with. Hiding a button in the app is never the only protection.",
  },
  {
    icon: Lock,
    title: "Medical data protection",
    text: "Records you have no relationship with simply return “not found”.",
    details: "Responses are shaped per role, so an authorized request still returns only the fields that role needs. Medical documents are visible to the patient and to doctors they have visits with; reception and administrators do not see them.",
  },
  {
    icon: HardDrive,
    title: "Transport and storage",
    text: "HTTPS in production, private object storage and secrets kept on the server.",
    details: "The hosted app and API are served over HTTPS. Files sit in a private Cloudflare R2 bucket; the API hands out a short-lived link only after checking that you may open the file. Credentials live in server environment variables, never in the browser bundle. We do not claim separate application-level encryption at rest.",
  },
  {
    icon: Sparkles,
    title: "AI privacy",
    text: "The assistant acts as you, with your permissions — never more.",
    details: "On free AI tiers the clinic keeps patient data away from the model: identifiers in messages are replaced before sending and record tools are switched off. The assistant cannot diagnose or prescribe, and every change it suggests needs your confirmation.",
  },
  {
    icon: ScrollText,
    title: "Auditability",
    text: "Sensitive administrative actions are written to an append-only audit log.",
    details: "Role changes, account activation and deactivation, admin invitations, doctor approvals and patient identity changes are recorded with who did them and when — in the same transaction as the change. Passwords and tokens are never recorded. This is not yet a full audit of every read.",
  },
];

// No billing exists in the application: nothing is sold or charged in the app.
// These cards describe how each kind of account is obtained today.
export const ACCESS_PLANS = [
  {
    name: "Patients",
    price: "No charge in the app",
    text: "Create an account yourself and start booking.",
    items: ["Doctor directory and online booking", "Appointment history", "AI assistant (daily message limit)", "Personal medical documents"],
    action: { to: "/register", label: "Create account" },
  },
  {
    name: "Doctors",
    price: "By application",
    text: "Apply with your professional details; an administrator reviews it.",
    items: ["Public profile in the directory", "Weekly availability and leave", "Own appointments and patients", "AI assistant for your schedule"],
    action: { to: "/register", label: "Apply as a doctor" },
    featured: true,
  },
  {
    name: "Clinic staff",
    price: "By invitation",
    text: "Receptionists and administrators are invited by the clinic.",
    items: ["Front desk booking and check-in", "User, doctor and department management", "Operational dashboards", "Audit trail of sensitive actions"],
    action: { to: "/login", label: "Sign in" },
  },
];

export const STEPS = [
  { title: "Create your account", text: "Register as a patient, or apply as a doctor. Staff accounts arrive by invitation." },
  { title: "Open your workspace", text: "You land on the dashboard for your role, with only the pages you can use." },
  { title: "Run the day", text: "Book and manage appointments, schedules, patients and documents." },
  { title: "Ask the assistant", text: "Find doctors, check slots or explain a report — every change waits for your confirmation." },
];

export const SHOWCASE = [
  {
    id: "admin",
    label: "Admin",
    title: "Admin dashboard",
    text: "A clinic-wide view: users, doctors, departments and every appointment, with approvals waiting in one place.",
    stats: [["Users", "18"], ["Doctors", "14"], ["Departments", "6"]],
    rows: [["Clinic Admin", "Administrator", "Active"], ["Sara Demo", "Receptionist", "Active"], ["Dr. Alex Sample", "Doctor", "Pending"]],
    cta: { to: "/login", label: "Sign in as admin" },
  },
  {
    id: "patient",
    label: "Patient",
    title: "Patient portal",
    text: "Upcoming visits, booking in a few taps and your documents — all in one place.",
    stats: [["Upcoming", "2"], ["Past visits", "5"], ["Documents", "3"]],
    rows: [["Dr. Alex Sample", "Cardiology · Thu 10:00", "Confirmed"], ["Dr. Rina Example", "Dermatology · Mon 14:30", "Scheduled"]],
    cta: { to: "/register", label: "Create a patient account" },
  },
  {
    id: "doctor",
    label: "Doctor",
    title: "Doctor workspace",
    text: "Today's list, your weekly availability and the patients you see — nothing else.",
    stats: [["Today", "6"], ["This week", "21"], ["Open slots", "9"]],
    rows: [["Jamie Demo", "09:30 · Follow-up", "Checked in"], ["Taylor Sample", "10:00 · Consultation", "Confirmed"]],
    cta: { to: "/register", label: "Apply as a doctor" },
  },
  {
    id: "reception",
    label: "Receptionist",
    title: "Front desk",
    text: "Find or register a patient, book on their behalf and keep the queue moving.",
    stats: [["Today", "32"], ["Checked in", "11"], ["Waiting", "4"]],
    rows: [["Morgan Demo", "Dr. Alex Sample · 11:00", "Waiting"], ["Casey Example", "Dr. Rina Example · 11:15", "Confirmed"]],
    cta: { to: "/login", label: "Staff sign in" },
  },
  {
    id: "assistant",
    label: "AI Assistant",
    title: "AI assistant",
    text: "Ask in plain language. Answers come from the clinic's data, and actions wait for your confirmation.",
    chat: [
      ["user", "Is a cardiologist free on Thursday morning?"],
      ["assistant", "Dr. Alex Sample has 09:30 and 10:00 free on Thursday. Shall I prepare a booking?"],
      ["user", "Yes, 10:00 please."],
      ["assistant", "Here is the booking — press Confirm to save it."],
    ],
    cta: { to: "/register", label: "Try it with an account" },
  },
];

export const FAQ = [
  ["What is Clinic AI Assistant?", "A clinic management web app: a public doctor directory, online booking, role-based workspaces for patients, doctors, receptionists and administrators, and an AI assistant that works with the clinic's own data."],
  ["Who can use the platform?", "Anyone can browse doctors and departments. Patients register themselves, doctors apply and are approved by an administrator, and receptionists and administrators are invited by the clinic."],
  ["How does the AI assistant work?", "After you sign in, the assistant answers questions using tools that read the clinic's database with your own permissions. It cannot see what you cannot see, and it has daily message limits."],
  ["Can patients book appointments online?", "Yes. Pick a doctor, choose one of their real free slots and confirm. You can also ask the assistant to prepare a booking and confirm it yourself."],
  ["Can doctors manage their schedules?", "Yes. Doctors set weekly availability and add leave or extra hours; free slots are computed from those settings."],
  ["Can I upload medical reports?", "Patients can keep documents on their record. Explanations by the assistant depend on the clinic's settings — document analysis by an external AI is off unless the clinic has an approved data agreement."],
  ["How is patient information protected?", "Every request is checked for permission and for your relationship to the record, sessions are short-lived, files are stored privately, and sensitive admin actions are audited. See the Security section for details."],
  ["Does the AI replace medical professionals?", "No. It gives general information and handles admin tasks. It does not diagnose or prescribe, and urgent symptoms get emergency guidance straight away."],
  ["Can the platform support multiple staff roles?", "Yes — patient, doctor, receptionist and administrator roles are built in, and a user can hold more than one role."],
  ["How do I get started?", "Create an account, or browse the doctor directory first without one."],
];

export const DEMO_STATS = [
  { label: "Users", value: "18", icon: Users, tone: "blue" },
  { label: "Doctors", value: "14", icon: Stethoscope, tone: "violet" },
  { label: "Appointments", value: "6", icon: CalendarCheck, tone: "amber" },
  { label: "Departments", value: "6", icon: Building2, tone: "pink" },
];
