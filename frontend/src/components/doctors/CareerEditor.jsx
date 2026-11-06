import { Briefcase, GraduationCap, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { NEW_POSITION, NEW_QUALIFICATION, toForm, toPayload } from "../../utils/career";
import Alert from "../Alert";

const YEAR_INPUT = { type: "number", min: 1940, max: 2100, step: 1, inputMode: "numeric" };

/**
 * The experience and/or education inputs. `section` ("experience" or
 * "education") shows one list only; the other stays in `form` untouched, so
 * saving never drops it.
 */
export function CareerFields({ form, onChange, section }) {
  const show = (name) => !section || section === name;
  const update = (list, index, field) => (e) =>
    onChange({ ...form, [list]: form[list].map((row, i) => (i === index ? { ...row, [field]: e.target.value } : row)) });
  const add = (list, empty) => onChange({ ...form, [list]: [...form[list], { ...empty }] });
  const remove = (list, index) => onChange({ ...form, [list]: form[list].filter((_, i) => i !== index) });

  return (
    <>
      {show("experience") && (
        <fieldset>
          <legend>
            <Briefcase size={18} aria-hidden="true" /> Experience
          </legend>
          {form.experience.length === 0 && <p className="muted small">No positions added.</p>}
          {form.experience.map((row, i) => (
            <div className="career-row" key={i} role="group" aria-label={`Position ${i + 1}`}>
              <label>
                Job title
                <input value={row.title} onChange={update("experience", i, "title")} maxLength={150} required />
              </label>
              <label>
                Hospital or organization
                <input value={row.organization} onChange={update("experience", i, "organization")} maxLength={200} required />
              </label>
              <label>
                Location
                <input value={row.location} onChange={update("experience", i, "location")} maxLength={150} />
              </label>
              <label className="year">
                From
                <input {...YEAR_INPUT} value={row.start_year} onChange={update("experience", i, "start_year")} required />
              </label>
              <label className="year">
                To
                <input {...YEAR_INPUT} value={row.end_year} onChange={update("experience", i, "end_year")} placeholder="Present" />
              </label>
              <label className="wide">
                Description
                <textarea value={row.description} onChange={update("experience", i, "description")} maxLength={1000} />
              </label>
              <button type="button" className="danger small-button" onClick={() => remove("experience", i)}>
                <Trash2 size={15} aria-hidden="true" /> Remove position
              </button>
            </div>
          ))}
          <button type="button" className="secondary small-button" onClick={() => add("experience", NEW_POSITION)}>
            <Plus size={15} aria-hidden="true" /> Add position
          </button>
        </fieldset>
      )}

      {show("education") && (
        <fieldset>
          <legend>
            <GraduationCap size={18} aria-hidden="true" /> Education
          </legend>
          {form.education.length === 0 && <p className="muted small">No qualifications added.</p>}
          {form.education.map((row, i) => (
            <div className="career-row" key={i} role="group" aria-label={`Qualification ${i + 1}`}>
              <label>
                Degree or qualification
                <input value={row.qualification} onChange={update("education", i, "qualification")} maxLength={150} required />
              </label>
              <label>
                Institution
                <input value={row.institution} onChange={update("education", i, "institution")} maxLength={200} required />
              </label>
              <label>
                Field of study
                <input value={row.field_of_study} onChange={update("education", i, "field_of_study")} maxLength={150} />
              </label>
              <label className="year">
                From
                <input {...YEAR_INPUT} value={row.start_year} onChange={update("education", i, "start_year")} />
              </label>
              <label className="year">
                To
                <input {...YEAR_INPUT} value={row.end_year} onChange={update("education", i, "end_year")} />
              </label>
              <button type="button" className="danger small-button" onClick={() => remove("education", i)}>
                <Trash2 size={15} aria-hidden="true" /> Remove qualification
              </button>
            </div>
          ))}
          <button type="button" className="secondary small-button" onClick={() => add("education", NEW_QUALIFICATION)}>
            <Plus size={15} aria-hidden="true" /> Add qualification
          </button>
        </fieldset>
      )}
    </>
  );
}

/**
 * Edit the experience and education shown on a doctor's public profile.
 * `load()` and `save(body)` call the API (own profile or, for admins, any
 * doctor); the server validates everything again and replaces the list.
 */
export default function CareerEditor({ load, save }) {
  const { data, loading, error } = useFetch(load, []);
  const [draft, setDraft] = useState(null); // null until the user changes something
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ error: "", notice: "" });
  const form = draft ?? (data ? toForm(data) : null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMessage({ error: "", notice: "" });
    try {
      const res = await save(toPayload(form));
      setDraft(toForm(res.data));
      setMessage({ error: "", notice: "Career history saved" });
    } catch (err) {
      setMessage({ error: getErrorMessage(err, "Could not save your career history"), notice: "" });
    } finally {
      setBusy(false);
    }
  };

  if (error) return <Alert>{error}</Alert>;
  if (loading || !form) return <div className="card skeleton" style={{ height: 160 }} role="status" aria-label="Loading career history" />;

  return (
    <form className="card career-editor" onSubmit={submit} aria-labelledby="career-editor-title">
      <h3 id="career-editor-title">Career history</h3>
      <p className="muted small">Shown on your public profile, newest first. Leave “To” blank for a current position.</p>

      <CareerFields form={form} onChange={setDraft} />

      <Alert>{message.error}</Alert>
      <Alert kind="success">{message.notice}</Alert>
      <button type="submit" disabled={busy}>
        {busy ? "Saving…" : "Save career history"}
      </button>
    </form>
  );
}
