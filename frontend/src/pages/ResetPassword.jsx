import { Navigate } from "react-router-dom";

/**
 * Emailed reset links (D126) were replaced by 6-digit codes (D127). An old
 * link still opens this address: it leads to Forgot password, where a code can
 * be requested. Any token in the address is dropped with it.
 */
export default function ResetPassword() {
  return <Navigate to="/forgot-password" replace />;
}
