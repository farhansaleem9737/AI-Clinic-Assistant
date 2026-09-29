import { Navigate } from "react-router-dom";
import { useAuth } from "../context/useAuth";

export default function AdminRoute({ children }) {
  const { user, token } = useAuth();

  if (!token) {
    return <Navigate to="/login" />;
  }

  if (!user) {
    return <p>Loading...</p>;
  }

  if (user.role !== "admin") {
    return <Navigate to="/dashboard" />;
  }

  return children;
}