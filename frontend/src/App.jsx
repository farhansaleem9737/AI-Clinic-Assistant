import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AuthLayout from "./layouts/AuthLayout";
import DirectoryLayout from "./layouts/DirectoryLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Doctors from "./pages/Doctors";
import { lazyPage } from "./routes/lazyPage";
import { PAGES, PROTECTED_ROUTES } from "./routes/pages";

// Pages load on demand (code splitting): only the entry pages, the dashboard and
// the layouts are in the main bundle. Each layout shows a page skeleton while a
// page's code downloads; a failed download is retried and can be tried again.
const LAZY = { ...Object.fromEntries(Object.entries(PAGES).map(([name, load]) => [name, lazyPage(load)])), Dashboard };
const { AcceptAdminInvite, Departments, DoctorDetail, ForgotPassword, LegalDocument, NotFound, Register } = LAZY;

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Signed-out pages: full-screen, without the app shell. */}
          <Route element={<AuthLayout variant="login" />}>
            <Route path="/login" element={<Login />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            {/* Public: reached from an emailed invitation link (D87). */}
            <Route path="/accept-admin-invite" element={<AcceptAdminInvite />} />
          </Route>
          <Route element={<AuthLayout variant="register" />}>
            <Route path="/register" element={<Register />} />
            <Route path="/terms" element={<LegalDocument document="terms" />} />
            <Route path="/privacy" element={<LegalDocument document="privacy" />} />
          </Route>
          {/* One branch for every page in the app shell, so signed-in users keep
              the same shell (and assistant) on every route. The directory pages
              are open to everyone: visitors get the public top navigation. */}
          <Route element={<DirectoryLayout />}>
            <Route path="/doctors" element={<Doctors />} />
            <Route path="/doctors/:id" element={<DoctorDetail />} />
            <Route path="/departments" element={<Departments />} />
            {PROTECTED_ROUTES.map(({ path, page, permission, anyOf, allOf }) => {
              const Page = LAZY[page];
              return (
                <Route
                  key={path}
                  path={path}
                  element={
                    <ProtectedRoute permission={permission} anyOf={anyOf} allOf={allOf}>
                      <Page />
                    </ProtectedRoute>
                  }
                />
              );
            })}
            <Route path="/" element={<Navigate to="/doctors" replace />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
