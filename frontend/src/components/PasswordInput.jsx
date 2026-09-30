import { Eye, EyeOff, Lock } from "lucide-react";
import { useState } from "react";

/**
 * Password field with a show/hide control. Toggling only changes the input
 * type; the value is untouched and never leaves component state.
 */
export default function PasswordInput({ id, value, onChange, invalid, describedBy, ...rest }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className={`input-icon${invalid ? " invalid" : ""}`}>
      <Lock size={18} aria-hidden="true" />
      <input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={onChange}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        {...rest}
      />
      <button
        type="button"
        className="icon-button"
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? <Eye size={18} aria-hidden="true" /> : <EyeOff size={18} aria-hidden="true" />}
      </button>
    </div>
  );
}
