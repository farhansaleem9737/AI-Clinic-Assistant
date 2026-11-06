import { Check, Info, Mail, MapPin, Pencil, Phone, Contact } from "lucide-react";
import { useMemo, useState } from "react";
import FormField from "../FormField";
import { useUnsavedChanges } from "../../hooks/useUnsavedChanges";
import { getErrorMessage } from "../../services/api";
import { updateMyDetails } from "../../services/patientService";
import { CITY_SUGGESTIONS, COUNTRY_OPTIONS, REGIONS, countryName, formatAddress } from "../../utils/locations";
import { contactErrors, joinPhone, splitPhone } from "../../utils/profileForms";
import { errorProps } from "../../utils/validation";

const fromProfile = (p) => {
  const country = p.country ?? "";
  const { dial, number } = splitPhone(p.phone, country || "PK");
  return { dial, number, email: p.email ?? "", address: p.address ?? "", city: p.city ?? "", province: p.province ?? "", country };
};

/** Only what changed; an untouched phone is never rewritten (no +92 added to a saved number). */
function changes(form, initial) {
  const out = {};
  if (form.dial !== initial.dial || form.number.trim() !== initial.number.trim()) out.phone = joinPhone(form.dial, form.number);
  for (const field of ["email", "address", "city", "province"]) {
    if (form[field].trim() !== initial[field].trim()) out[field] = form[field].trim() || null;
  }
  if (form.country !== initial.country) out.country = form.country || null;
  return out;
}

function Overview({ profile, signInEmail }) {
  const address = formatAddress(profile);
  return (
    <section className="card pp-contact-overview" aria-labelledby="contact-overview-title">
      <h2 id="contact-overview-title">
        <Contact size={22} aria-hidden="true" /> Contact Overview
      </h2>
      <dl className="pp-contact-list">
        <div>
          <dt>
            <Phone size={18} aria-hidden="true" /> Phone
          </dt>
          <dd>{profile.phone || <span className="muted">Not provided</span>}</dd>
        </div>
        <div>
          <dt>
            <Mail size={18} aria-hidden="true" /> Email
          </dt>
          <dd>{profile.email || <span className="muted">Not provided</span>}</dd>
        </div>
        <div>
          <dt>
            <MapPin size={18} aria-hidden="true" /> Address
          </dt>
          <dd>{address || <span className="muted">Not provided</span>}</dd>
        </div>
      </dl>
      <div className="pp-why">
        <Info size={20} aria-hidden="true" />
        <div>
          <h3>Why we need this?</h3>
          <p className="muted small">To send appointment updates, reminders, and important clinic notifications.</p>
        </div>
      </div>
      {signInEmail && (
        <p className="muted small pp-signin">
          You sign in with <strong>{signInEmail}</strong>; that address is changed only by the clinic. The email above is how the clinic contacts you.
        </p>
      )}
    </section>
  );
}

/**
 * Contact Information (D111): what is saved, and the form to change it. The
 * contact email is not the sign-in email: changing it never touches the login.
 */
export default function ContactSection({ profile, signInEmail, onSaved }) {
  const initial = useMemo(() => fromProfile(profile), [profile]);
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = changes(form, initial);
  const dirty = Object.keys(pending).length > 0;
  useUnsavedChanges(dirty);
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });
  const regions = REGIONS[form.country];
  const cities = CITY_SUGGESTIONS[form.country] ?? [];

  const setCountry = (e) => {
    const country = e.target.value;
    const keepProvince = !REGIONS[country] || REGIONS[country].includes(form.province);
    const dial = COUNTRY_OPTIONS.find((c) => c.code === country)?.dial;
    setForm({ ...form, country, province: keepProvince ? form.province : "", dial: form.number.trim() ? form.dial : (dial ?? form.dial) });
  };
  const cancel = () => {
    setForm(initial);
    setErrors({});
    setError("");
  };
  const save = async (e) => {
    e.preventDefault();
    if (busy || !dirty) return;
    const found = contactErrors(form, { phoneChanged: "phone" in pending });
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      const updated = (await updateMyDetails(pending)).data;
      onSaved(updated, "Your contact details were saved.");
      setForm(fromProfile(updated));
    } catch (err) {
      setError(getErrorMessage(err, "Your changes could not be saved. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pp-layout">
      <Overview profile={profile} signInEmail={signInEmail} />
      <form className="card pp-form" onSubmit={save} noValidate aria-labelledby="update-contact-title">
        <h2 id="update-contact-title">
          <Pencil size={20} aria-hidden="true" /> Update Contact Details
        </h2>
        <div className="pp-grid">
          <FormField id="pp-phone" label="Phone Number *" error={errors.number}>
            <div className="pp-phone">
              <select aria-label="Country calling code" value={form.dial} onChange={set("dial")}>
                {[...new Map(COUNTRY_OPTIONS.map((c) => [c.dial, c])).values()].map((c) => (
                  <option key={c.dial} value={c.dial}>
                    {c.code} +{c.dial}
                  </option>
                ))}
              </select>
              <input id="pp-phone" type="tel" inputMode="tel" autoComplete="tel-national" value={form.number} onChange={set("number")} placeholder="3001234567" {...errorProps("pp-phone", errors.number)} />
            </div>
          </FormField>
          <FormField id="pp-email" label="Email Address *" error={errors.email}>
            <div className="pp-input-icon">
              <Mail size={17} aria-hidden="true" />
              <input id="pp-email" type="email" autoComplete="email" value={form.email} onChange={set("email")} {...errorProps("pp-email", errors.email)} />
            </div>
          </FormField>
          <div className="pp-wide">
            <FormField id="pp-address" label="Address *" error={errors.address}>
              <div className="pp-input-icon">
                <MapPin size={17} aria-hidden="true" />
                <input id="pp-address" value={form.address} maxLength={500} autoComplete="street-address" placeholder="House, street, area" onChange={set("address")} {...errorProps("pp-address", errors.address)} />
              </div>
            </FormField>
          </div>
          <div className="pp-wide pp-place">
            <FormField id="pp-city" label="City *" error={errors.city}>
              <input id="pp-city" list="pp-city-options" value={form.city} maxLength={100} autoComplete="address-level2" onChange={set("city")} {...errorProps("pp-city", errors.city)} />
              <datalist id="pp-city-options">
                {cities.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </FormField>
            <FormField id="pp-province" label="Province / State *" error={errors.province}>
              {regions ? (
                <select id="pp-province" value={form.province} onChange={set("province")} {...errorProps("pp-province", errors.province)}>
                  <option value="">Choose…</option>
                  {/* A saved value outside the list is kept, never silently replaced. */}
                  {form.province && !regions.includes(form.province) && <option value={form.province}>{form.province}</option>}
                  {regions.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              ) : (
                <input id="pp-province" value={form.province} maxLength={100} autoComplete="address-level1" onChange={set("province")} {...errorProps("pp-province", errors.province)} />
              )}
            </FormField>
            <FormField id="pp-country" label="Country *" error={errors.country}>
              <select id="pp-country" value={form.country} onChange={setCountry} {...errorProps("pp-country", errors.country)}>
                <option value="">Choose…</option>
                {COUNTRY_OPTIONS.map((c) => (
                  <option key={c.code} value={c.code}>
                    {countryName(c.code)}
                  </option>
                ))}
                {form.country && !COUNTRY_OPTIONS.some((c) => c.code === form.country) && <option value={form.country}>{countryName(form.country)}</option>}
              </select>
            </FormField>
          </div>
        </div>
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <div className="pp-actions">
          <button type="button" className="secondary" onClick={cancel} disabled={busy || !dirty}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !dirty} aria-busy={busy}>
            <Check size={17} aria-hidden="true" /> {busy ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </form>
    </div>
  );
}
