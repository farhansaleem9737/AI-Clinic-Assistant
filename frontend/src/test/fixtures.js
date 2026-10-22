// Shapes returned by the API, for tests.

export function appointment(overrides = {}) {
  return {
    id: "appt-1",
    status: "confirmed",
    starts_at: "2026-10-05T05:00:00Z",
    ends_at: "2026-10-05T05:30:00Z",
    timezone: "Asia/Karachi",
    reason: null,
    doctor: {
      id: "doc-1",
      name: "Sarah Khan",
      title: "Dr.",
      room_number: "B-12",
      specialization: "Cardiologist",
      department_id: "dep-1",
      department_name: "Cardiology",
      years_of_experience: 10,
      is_verified: true,
    },
    patient: { id: "pat-1", mrn: "MRN00000001", name: "John Doe", date_of_birth: "1990-01-01" },
    cancellation_reason: null,
    cancellation_note: null,
    cancelled_at: null,
    rescheduled_from_id: null,
    rescheduled_to_id: null,
    allowed_transitions: [],
    can_reschedule: false,
    created_at: "2026-09-28T10:00:00Z",
    updated_at: "2026-09-28T10:00:00Z",
    ...overrides,
  };
}

// GET /appointments/{id} adds the patient's profile to the list shape.
export function appointmentDetail(overrides = {}) {
  return appointment({
    patient_profile: {
      sex_at_birth: "male",
      phone: "+1 234 567 890",
      email: "john@example.com",
      address: "123 Main St, City",
    },
    ...overrides,
  });
}

export const page = (items) => ({ data: { items, total: items.length, page: 1, page_size: 20 } });

const today = {
  date: "2026-10-05",
  timezone: "Asia/Karachi",
  total: 6,
  awaiting_check_in: 3,
  checked_in: 1,
  in_progress: 1,
  completed: 0,
  cancelled: 1,
  no_show: 0,
};

export const summaries = {
  patient: {
    account: { is_active: true, roles: ["patient"] },
    patient: { has_profile: true, profile_active: true, upcoming_appointments: 2, total_appointments: 5, my_doctors: 3 },
    doctor: null,
    front_desk: null,
    overview: null,
  },
  doctor: {
    account: { is_active: true, roles: ["doctor"] },
    patient: null,
    doctor: { has_profile: true, today, upcoming_appointments: 9, my_patients: 14 },
    front_desk: null,
    overview: null,
  },
  receptionist: {
    account: { is_active: true, roles: ["receptionist"] },
    patient: null,
    doctor: null,
    front_desk: { today, upcoming_appointments: 40 },
    overview: {
      users_total: null,
      users_active: null,
      doctors_active: 7,
      departments_active: null,
      patients_total: 120,
      patients_active: 118,
      appointments_total: 300,
    },
  },
  admin: {
    account: { is_active: true, roles: ["admin"] },
    patient: null,
    doctor: null,
    front_desk: { today, upcoming_appointments: 40 },
    overview: {
      users_total: 25,
      users_active: 24,
      doctors_active: 7,
      departments_active: 5,
      patients_total: 120,
      patients_active: 118,
      appointments_total: 300,
    },
  },
  noRole: { account: { is_active: true, roles: [] }, patient: null, doctor: null, front_desk: null, overview: null },
};

export const patientProfile = {
  id: "pat-1",
  mrn: "MRN00000001",
  first_name: "John",
  last_name: "Doe",
  date_of_birth: "1990-01-01",
  sex_at_birth: "male",
  phone: "+1 234 567 890",
  email: "john@example.com",
  address: "123 Main St",
};

export const doctorProfile = {
  id: "doc-1",
  name: "Sarah Khan",
  title: "Dr.",
  specialization: "Cardiologist",
  department_name: "Cardiology",
  room_number: "B-12",
  license_number: "PMC-1",
  years_of_experience: 10,
  consultation_fee: "150.00",
};

// What useAuth() returns for a user holding exactly these permissions.
export function authAs(name, roles, permissions) {
  return {
    user: {
      id: "u-1",
      name,
      email: "user@example.com",
      roles,
      permissions,
      doctor_id: roles.includes("doctor") ? "doc-1" : null,
      patient_id: roles.includes("patient") ? "pat-1" : null,
    },
    initializing: false,
    can: (permission) => permissions.includes(permission),
    hasRole: (role) => roles.includes(role),
    logout: async () => {},
  };
}

export const PERMISSIONS = {
  patient: ["appointment:read_own", "appointment:create_own", "patient:read_own", "patient:update_own", "availability:read"],
  doctor: ["appointment:read_assigned", "appointment:consult", "doctor:update_own", "schedule:manage_own", "patient:read_assigned"],
  receptionist: [
    "appointment:read_any",
    "appointment:create",
    "appointment:check_in",
    "patient:read_any",
    "patient:create",
    "schedule:manage_any",
    "doctor:read",
  ],
  admin: [
    "appointment:read_any",
    "appointment:create",
    "patient:read_any",
    "schedule:manage_any",
    "doctor:read",
    "department:manage",
    "user:read",
  ],
};

// One entry of GET /public/doctors (also the body of GET /public/doctors/{id}).
export function publicDoctor(overrides = {}) {
  return {
    id: "doc-1",
    name: "Sarah Khan",
    title: "Dr.",
    specialization: "Cardiologist",
    department_id: "dep-1",
    department_name: "Cardiology",
    years_of_experience: 10,
    consultation_fee: "150.00",
    qualifications: "MBBS, FCPS (Cardiology)",
    bio: "Treats heart conditions.",
    is_verified: true,
    availability: { status: "available", next_available: "2026-10-05T04:00:00Z" },
    ...overrides,
  };
}

export const doctorsPage = (items, extra = {}) => ({
  data: { items, total: items.length, page: 1, page_size: 6, total_pages: items.length ? 1 : 0, ...extra },
});

// What useAuth() returns for a visitor who is not signed in.
export const anonymous = { user: null, initializing: false, can: () => false, hasRole: () => false, logout: async () => {} };
