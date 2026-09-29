import { useEffect, useState } from "react";
import { getErrorMessage } from "../services/api";
import { getDoctors, createDoctor } from "../services/doctorService";
import { getDepartments } from "../services/departmentService";

// Fields that must never hold a negative value: IDs, experience and fee.
const NON_NEGATIVE_FIELDS = [
  "user_id",
  "department_id",
  "years_of_experience",
  "consultation_fee",
];

// Keeps whatever the user typed (so the field can still be cleared or hold a
// decimal fee) but never lets a negative value reach state.
const clampNonNegative = (value) => (Number(value) < 0 ? "0" : value);

// Final clamp on the way to the backend: "" / NaN / negative all become 0.
const toNonNegativeNumber = (value) => Math.max(0, Number(value) || 0);

export default function AdminDoctors() {
  const [doctors, setDoctors] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [form, setForm] = useState({
    user_id: "",
    department_id: "",
    specialization: "",
    bio: "",
    years_of_experience: 0,
    consultation_fee: "",
  });
  const [error, setError] = useState("");

  const loadData = () => {
    getDoctors().then((res) => setDoctors(res.data)).catch(() => {});
    getDepartments().then((res) => setDepartments(res.data)).catch(() => {});
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm({
      ...form,
      [name]: NON_NEGATIVE_FIELDS.includes(name) ? clampNonNegative(value) : value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      await createDoctor({
        ...form,
        user_id: toNonNegativeNumber(form.user_id),
        department_id: toNonNegativeNumber(form.department_id),
        years_of_experience: toNonNegativeNumber(form.years_of_experience),
        consultation_fee: form.consultation_fee
          ? toNonNegativeNumber(form.consultation_fee)
          : null,
      });
      setForm({
        user_id: "",
        department_id: "",
        specialization: "",
        bio: "",
        years_of_experience: 0,
        consultation_fee: "",
      });
      loadData();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create doctor"));
    }
  };

  return (
    <div>
      <h2>Manage Doctors</h2>

      <form onSubmit={handleSubmit}>
        {error && <p style={{ color: "red" }}>{error}</p>}

        <input
          type="number"
          name="user_id"
          min="0"
          placeholder="User ID (must have role=doctor)"
          value={form.user_id}
          onChange={handleChange}
          required
        />

        <select name="department_id" value={form.department_id} onChange={handleChange} required>
          <option value="">Select department</option>
          {departments.map((dept) => (
            <option key={dept.id} value={dept.id}>
              {dept.name}
            </option>
          ))}
        </select>

        <input
          type="text"
          name="specialization"
          placeholder="Specialization"
          value={form.specialization}
          onChange={handleChange}
          required
        />

        <input
          type="text"
          name="bio"
          placeholder="Bio"
          value={form.bio}
          onChange={handleChange}
        />

        <input
          type="number"
          name="years_of_experience"
          min="0"
          placeholder="Years of experience"
          value={form.years_of_experience}
          onChange={handleChange}
        />

        <input
          type="number"
          name="consultation_fee"
          min="0"
          placeholder="Consultation fee"
          value={form.consultation_fee}
          onChange={handleChange}
        />

        <button type="submit">Create Doctor</button>
      </form>

      <h3>Existing Doctors</h3>
      <ul>
        {doctors.map((doc) => (
          <li key={doc.id}>
            {doc.name} — {doc.specialization} — Dept #{doc.department_id} —{" "}
            {doc.years_of_experience} yrs
          </li>
        ))}
      </ul>
    </div>
  );
}