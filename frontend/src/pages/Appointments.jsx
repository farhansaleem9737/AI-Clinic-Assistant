import { useAuth } from "../context/useAuth";
import DoctorAppointments from "./DoctorAppointments";
import PatientAppointments from "./PatientAppointments";
import ReceptionAppointments from "./ReceptionAppointments";

// One route, a view per kind of reader. The API decides what each may see.
export default function Appointments() {
  const { user, can } = useAuth();
  const patientOnly = can("appointment:read_own") && !can("appointment:read_any") && !can("appointment:read_assigned");
  if (patientOnly) return <PatientAppointments />;
  // A doctor's own appointments: the My Appointments day view (D79).
  if (can("appointment:read_assigned") && !can("appointment:read_any") && user.doctor_id) return <DoctorAppointments />;
  // Front desk and administrators: every appointment they may manage (D84).
  return <ReceptionAppointments />;
}
