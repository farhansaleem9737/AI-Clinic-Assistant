import { useEffect } from "react";
import { useAuth } from "../context/useAuth";

export default function Dashboard() {
  const { user, fetchCurrentUser, logout } = useAuth();

  useEffect(() => {
    if (!user) {
      fetchCurrentUser();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  if (!user) return <p>Loading...</p>;

  return (
    <div>
      <h2>Welcome, {user.name}</h2>
      <p>Email: {user.email}</p>
      <p>Role: {user.role}</p>
      <button onClick={logout}>Logout</button>
    </div>
  );
}