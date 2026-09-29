import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./layouts/AppLayout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Doctors from "./pages/Doctors";
import DoctorDetail from "./pages/DoctorDetail";
import MyDoctorProfile from "./pages/MyDoctorProfile";
import AdminDepartments from "./pages/AdminDepartments";
import AdminDoctors from "./pages/AdminDoctors";
import AdminUsers from "./pages/AdminUsers";

// `permission` on a route only hides pages the user cannot use; the API
// enforces the same permission on every request.
const PROTECTED_ROUTES = [
  { path: "/dashboard", element: <Dashboard /> },
  { path: "/doctor/profile", element: <MyDoctorProfile />, permission: "doctor:update_own" },
  { path: "/admin/users", element: <AdminUsers />, permission: "user:read" },
  { path: "/admin/departments", element: <AdminDepartments />, permission: "department:manage" },
  { path: "/admin/doctors", element: <AdminDoctors />, permission: "doctor:read" },
];

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/doctors" element={<Doctors />} />
            <Route path="/doctors/:id" element={<DoctorDetail />} />
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
