import { useEffect, useState } from "react";
import { getErrorMessage } from "../services/api";
import { getDepartments, createDepartment } from "../services/departmentService";

export default function AdminDepartments() {
  const [departments, setDepartments] = useState([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  const loadDepartments = () => {
    getDepartments()
      .then((res) => setDepartments(res.data))
      .catch(() => setError("Failed to load departments"));
  };

  useEffect(() => {
    loadDepartments();
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      await createDepartment({ name, description });
      setName("");
      setDescription("");
      loadDepartments();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create department"));
    }
  };

  return (
    <div>
      <h2>Manage Departments</h2>

      <form onSubmit={handleSubmit}>
        {error && <p style={{ color: "red" }}>{error}</p>}
        <input
          type="text"
          placeholder="Department name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <input
          type="text"
          placeholder="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <button type="submit">Create Department</button>
      </form>

      <h3>Existing Departments</h3>
      <ul>
        {departments.map((dept) => (
          <li key={dept.id}>
            <strong>{dept.name}</strong> — {dept.description}
          </li>
        ))}
      </ul>
    </div>
  );
}