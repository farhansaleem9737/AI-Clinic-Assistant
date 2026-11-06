import { useEffect } from "react";

export const LEAVE_MESSAGE = "You have unsaved changes. Leave this page without saving them?";

/**
 * While `dirty`, asks before the user leaves with unsaved changes: closing or
 * reloading the tab (the browser's own prompt) and following a link inside
 * the app (a confirm). The browser's Back button is not covered: the app's
 * router (BrowserRouter) cannot hold a navigation back.
 */
export function useUnsavedChanges(dirty) {
  useEffect(() => {
    if (!dirty) return undefined;
    const beforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = ""; // older browsers need it set
    };
    const onClick = (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
      const link = event.target.closest?.("a[href]");
      if (!link || link.target === "_blank" || link.origin !== window.location.origin) return;
      if (link.pathname === window.location.pathname && link.search === window.location.search) return;
      if (!window.confirm(LEAVE_MESSAGE)) {
        event.preventDefault();
        event.stopPropagation(); // the router's own handler must not navigate either
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", onClick, true); // before React Router's link handler
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);
}
