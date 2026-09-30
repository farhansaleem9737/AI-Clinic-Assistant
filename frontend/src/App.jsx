import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./layouts/AppLayout";
import AuthLayout from "./layouts/AuthLayout";
import ForgotPassword from "./pages/ForgotPassword";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Departments from "./pages/Departments";
import Doctors from "./pages/Doctors";
import DoctorDetail from "./pages/DoctorDetail";
import MyDoctorProfile from "./pages/MyDoctorProfile";
import MyPatientProfile from "./pages/MyPatientProfile";
import Patients from "./pages/Patients";
import PatientDetail from "./pages/PatientDetail";
import AdminDepartments from "./pages/AdminDepartments";
import AdminDoctors from "./pages/AdminDoctors";
import AdminUsers from "./pages/AdminUsers";
import Appointments from "./pages/Appointments";
import AppointmentDetail from "./pages/AppointmentDetail";
import BookAppointment from "./pages/BookAppointment";
import DoctorSchedule from "./pages/DoctorSchedule";

// `permission` on a route only hides pages the user cannot use; the API
// enforces the same permission on every request.
const APPOINTMENT_READ = ["appointment:read_own", "appointment:read_assigned", "appointment:read_any"];

const PROTECTED_ROUTES = [
  { path: "/dashboard", element: <Dashboard /> },
  { path: "/appointments", element: <Appointments />, anyOf: APPOINTMENT_READ },
  { path: "/appointments/book", element: <BookAppointment />, anyOf: ["appointment:create", "appointment:create_own"] },
  { path: "/appointments/:id", element: <AppointmentDetail />, anyOf: APPOINTMENT_READ },
  { path: "/schedule", element: <DoctorSchedule />, anyOf: ["schedule:manage_own", "schedule:manage_any"] },
  { path: "/doctor/profile", element: <MyDoctorProfile />, permission: "doctor:update_own" },
  { path: "/profile", element: <MyPatientProfile />, permission: "patient:read_own" },
  { path: "/patients", element: <Patients />, permission: "patient:read_any" },
  { path: "/patients/:id", element: <PatientDetail />, anyOf: ["patient:read_any", "patient:read_assigned"] },
  { path: "/admin/users", element: <AdminUsers />, permission: "user:read" },
  { path: "/admin/departments", element: <AdminDepartments />, permission: "department:manage" },
  { path: "/admin/doctors", element: <AdminDoctors />, permission: "doctor:read" },
];

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Signed-out pages: full-screen, without the app shell. */}
          <Route element={<AuthLayout />}>
            <Route path="/login" element={<Login />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
          </Route>
          <Route element={<AppLayout />}>
            <Route path="/register" element={<Register />} />
            <Route path="/doctors" element={<Doctors />} />
            <Route path="/doctors/:id" element={<DoctorDetail />} />
            <Route path="/departments" element={<Departments />} />
            {PROTECTED_ROUTES.map(({ path, element, permission, anyOf }) => (
              <Route
                key={path}
                path={path}
                element={
                  <ProtectedRoute permission={permission} anyOf={anyOf}>
                    {element}
                  </ProtectedRoute>
                }
              />
            ))}
            <Route path="/" element={<Navigate to="/doctors" replace />} />
            <Route path="*" element={<p>Page not found.</p>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
