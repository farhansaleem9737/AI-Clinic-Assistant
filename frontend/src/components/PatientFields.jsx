import { SEX_LABELS, SEX_OPTIONS } from "../utils/patient";

// Demographic + contact fields shared by registration, walk-in and edit forms.
export default function PatientFields({ values, onChange, identity = true, contact = true }) {
  const field = (name) => ({ value: values[name] ?? "", onChange: (e) => onChange({ ...values, [name]: e.target.value }) });
  return (
    <>
      {identity && (
        <>
          <div className="row">
            <label style={{ flex: 1 }}>
              First name
              <input {...field("first_name")} required />
            </label>
            <label style={{ flex: 1 }}>
              Last name
              <input {...field("last_name")} required />
            </label>
          </div>
          <div className="row">
            <label>
              Date of birth
              <input type="date" {...field("date_of_birth")} max={new Date().toISOString().slice(0, 10)} required />
            </label>
            <label>
              Gender
              <select {...field("sex_at_birth")}>
                {SEX_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {SEX_LABELS[s]}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </>
      )}
      {contact && (
        <>
          <div className="row">
            <label style={{ flex: 1 }}>
              Phone
              <input {...field("phone")} />
            </label>
            <label style={{ flex: 1 }}>
              Contact email
              <input type="email" {...field("email")} />
            </label>
          </div>
          <label>
            Address
            <input {...field("address")} />
          </label>
          <label>
            Preferred language
            <input {...field("preferred_language")} />
          </label>
        </>
      )}
    </>
  );
}
