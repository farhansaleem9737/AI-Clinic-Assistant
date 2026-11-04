import { matchPath, useLocation } from "react-router-dom";
import { useAuth } from "../context/useAuth";
import AppLayout from "./AppLayout";
import PublicLayout from "./PublicLayout";

// The pages anyone can open.
const DIRECTORY = ["/doctors", "/doctors/:id", "/departments"];

/**
 * Layout for every page inside the app shell. Signed-in users always get the
 * same AppLayout, so moving between the directory and their own pages never
 * remounts the shell (the assistant's conversation and the sidebar stay as
 * they are, D107). Visitors get the public top navigation on the directory
 * pages; while a session is being restored there nothing is decided yet, so
 * neither layout flashes on screen.
 */
export default function DirectoryLayout() {
  const { user, initializing } = useAuth();
  const { pathname } = useLocation();
  const directory = DIRECTORY.some((pattern) => matchPath(pattern, pathname));
  if (user || !directory) return <AppLayout />;
  if (initializing) return <p className="muted page-loading" role="status">Loading…</p>;
  return <PublicLayout />;
}
