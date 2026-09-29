import { useEffect, useState } from "react";
import Alert from "../components/Alert";
import { getErrorMessage } from "../services/api";
import { getMyDoctorProfile, updateMyDoctorProfile } from "../services/doctorService";
import { doctorName, formatFee } from "../utils/format";

export default function MyDoctorProfile() {
  const [profile, setProfile] = useState(null);
  const [form, setForm] = useState({ bio: "", phone: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    getMyDoctorProfile()
      .then((res) => {
        setProfile(res.data);
        setForm({ bio: res.data.bio ?? "", phone: res.data.phone ?? "" });
      })
      .catch((err) => setError(getErrorMessage(err, "Could not load your profile")));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setNotice("");
    try {
      const res = await updateMyDoctorProfile({ bio: form.bio || null, phone: form.phone || null });
      setProfile(res.data);
      setNotice("Profile saved");
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  if (!profile) return error ? <Alert>{error}</Alert> : <p className="muted">Loading…</p>;

  return (
    <div>
      <h2>My profile</h2>
      <div className="card">
        <h3>{doctorName(profile)}</h3>
        <p className="muted">
          {profile.specialization} · {profile.department_name}
        </p>
        <p className="small">
          License: {profile.license_number ?? "—"} · Room: {profile.room_number ?? "—"} · Fee:{" "}
          {formatFee(profile.consultation_fee)}
        </p>
        <p className="muted small">Department, license, room and fee are managed by the clinic administration.</p>
      </div>
      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>
      <form className="card stack" onSubmit={handleSubmit}>
        <label>
          Bio (shown in the public directory)
          <textarea value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} maxLength={1000} />
        </label>
        <label>
          Phone (internal only)
          <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} maxLength={30} />
        </label>
        <button type="submit">Save</button>
      </form>
    </div>
  );
}
