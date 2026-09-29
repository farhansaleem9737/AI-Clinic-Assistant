import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Alert from "../components/Alert";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { getPublicDoctor } from "../services/doctorService";
import { doctorName, formatFee } from "../utils/format";

export default function DoctorDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [doctor, setDoctor] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getPublicDoctor(id)
      .then((res) => setDoctor(res.data))
      .catch((err) => setError(getErrorMessage(err, "Doctor not found")));
  }, [id]);

  if (error) return <Alert>{error}</Alert>;
  if (!doctor) return <p className="muted">Loading…</p>;

  return (
    <div className="card">
      <p>
        <Link to="/doctors">← All doctors</Link>
      </p>
      <h2>{doctorName(doctor)}</h2>
      <p className="muted">
        {doctor.specialization} · {doctor.department_name}
      </p>
      {doctor.bio && <p>{doctor.bio}</p>}
      <p>{doctor.years_of_experience} years experience</p>
      <p>Consultation fee: {formatFee(doctor.consultation_fee)}</p>
      {can("appointment:create_own") && (
        <Link to={`/appointments/book?doctor=${doctor.id}`}>
          <button>Book an appointment</button>
        </Link>
      )}
    </div>
  );
}
