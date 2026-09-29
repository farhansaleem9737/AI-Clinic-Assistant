import { useEffect, useState } from "react";
import { getDoctors } from "../services/doctorService";

export default function Doctors() {
  const [doctors, setDoctors] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getDoctors()
      .then((res) => setDoctors(res.data))
      .catch(() => setError("Failed to load doctors"));
  }, []);

  return (
    <div>
      <h2>Our Doctors</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}
      {doctors.length === 0 && !error && <p>No doctors listed yet.</p>}
      <div>
        {doctors.map((doc) => (
          <div key={doc.id} style={{ border: "1px solid #ccc", padding: "1rem", marginBottom: "1rem" }}>
            <h3>{doc.name} — {doc.specialization}</h3>
            <p>{doc.bio}</p>
            <p>Experience: {doc.years_of_experience} years</p>
            {doc.consultation_fee && <p>Fee: ${doc.consultation_fee}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}