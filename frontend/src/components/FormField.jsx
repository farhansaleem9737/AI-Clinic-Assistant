/**
 * A labelled form field with its error message. The error is linked to the
 * control by id (`<id>-error`), which the control references through
 * aria-describedby (see errorProps in utils/validation.js).
 */
export default function FormField({ id, label, error, children }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {error && (
        <p id={`${id}-error`} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
