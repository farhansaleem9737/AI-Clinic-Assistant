import { CURRENCY } from "../../utils/format";
import { errorProps } from "../../utils/validation";
import FormField from "../FormField";

// Suggestions only: any regulator in any country can be typed.
const AUTHORITIES = [
  "Pakistan Medical and Dental Council (PMDC)",
  "General Medical Council (GMC)",
  "National Medical Commission (NMC)",
  "Medical Council of Ireland",
  "Saudi Commission for Health Specialties",
  "Dubai Health Authority (DHA)",
];
const LANGUAGES = ["English", "Urdu", "Punjabi", "Sindhi", "Pashto", "Arabic", "Hindi"];

const optional = (label) => (
  <>
    {label} <span className="optional">(optional)</span>
  </>
);

/**
 * The doctor's professional details, all optional (D77). Controlled:
 * `values` holds strings, `onChange(field, value)` updates one. Used on the
 * registration page and on the application page, so both ask the same way.
 */
export default function ProfessionalFields({
  idPrefix,
  values,
  errors = {},
  onChange,
  departments,
  departmentsError,
  disabled = false,
}) {
  const id = (field) => `${idPrefix}-${field.replace(/_/g, "-")}`;
  const bind = (field) => ({
    id: id(field),
    name: field,
    className: "control",
    value: values[field],
    disabled,
    onChange: (e) => onChange(field, e.target.value),
    ...errorProps(id(field), errors[field]),
  });

  return (
    <div className="pro-fields">
      <FormField id={id("license_number")} label={optional("Medical License Number")} error={errors.license_number}>
        <input maxLength={50} placeholder="Enter your medical registration/license number" {...bind("license_number")} />
      </FormField>

      <FormField
        id={id("registration_authority")}
        label={optional("Medical Registration Authority")}
        error={errors.registration_authority}
      >
        <input
          maxLength={150}
          list={`${idPrefix}-authorities`}
          placeholder="Select or enter registration authority"
          {...bind("registration_authority")}
        />
        <datalist id={`${idPrefix}-authorities`}>
          {AUTHORITIES.map((a) => (
            <option key={a} value={a} />
          ))}
        </datalist>
      </FormField>

      <FormField id={id("specialization")} label={optional("Specialization")} error={errors.specialization}>
        <input maxLength={150} placeholder="Enter your medical specialization" {...bind("specialization")} />
      </FormField>

      <FormField id={id("department_id")} label={optional("Department")} error={errors.department_id}>
        <select {...bind("department_id")} disabled={disabled || !departments?.length}>
          <option value="">{departments ? "Select department" : "Loading departments…"}</option>
          {departments?.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        {departmentsError && <p className="field-hint">{departmentsError}</p>}
      </FormField>

      <div className="pro-fields-row">
        <FormField
          id={id("years_of_experience")}
          label={optional("Years of Experience")}
          error={errors.years_of_experience}
        >
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={80}
            step={1}
            placeholder="Enter years of professional experience"
            {...bind("years_of_experience")}
          />
        </FormField>
        <FormField
          id={id("consultation_fee")}
          label={optional(CURRENCY ? `Consultation Fee (${CURRENCY})` : "Consultation Fee")}
          error={errors.consultation_fee}
        >
          <input
            type="number"
            inputMode="decimal"
            min={0}
            step="0.01"
            placeholder="Enter consultation fee"
            {...bind("consultation_fee")}
          />
        </FormField>
      </div>

      <FormField
        id={id("qualifications")}
        label={optional("Medical Qualification / Degree")}
        error={errors.qualifications}
      >
        <input maxLength={500} placeholder="e.g., MBBS, MD, FCPS" {...bind("qualifications")} />
      </FormField>

      <FormField id={id("institution")} label={optional("Medical Institution / University")} error={errors.institution}>
        <input maxLength={200} placeholder="Enter your institution or university" {...bind("institution")} />
      </FormField>

      <FormField id={id("languages")} label={optional("Languages Spoken")} error={errors.languages}>
        <input
          maxLength={200}
          list={`${idPrefix}-languages`}
          placeholder="Enter or select languages"
          {...bind("languages")}
          aria-describedby={errors.languages ? `${id("languages")}-error` : `${id("languages")}-hint`}
        />
        <datalist id={`${idPrefix}-languages`}>
          {LANGUAGES.map((l) => (
            <option key={l} value={l} />
          ))}
        </datalist>
        {!errors.languages && (
          <p id={`${id("languages")}-hint`} className="field-hint">
            Separate languages with commas, e.g. English, Urdu.
          </p>
        )}
      </FormField>

      <FormField id={id("bio")} label={optional("Professional Biography")} error={errors.bio}>
        <textarea
          rows={4}
          maxLength={1000}
          placeholder="Tell patients about your medical background and experience"
          {...bind("bio")}
        />
      </FormField>
    </div>
  );
}
