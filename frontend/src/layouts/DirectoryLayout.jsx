import { useAuth } from "../context/useAuth";
import AppLayout from "./AppLayout";
import PublicLayout from "./PublicLayout";

/**
 * Layout for the pages anyone can open (doctors, departments): visitors get
 * the public top navigation, signed-in users stay inside their app shell.
 * While a session is being restored nothing is decided yet, so neither
 * layout flashes on screen.
 */
export default function DirectoryLayout() {
  const { user, initializing } = useAuth();
  if (initializing) return <p className="muted page-loading" role="status">Loading…</p>;
  return user ? <AppLayout /> : <PublicLayout />;
}
