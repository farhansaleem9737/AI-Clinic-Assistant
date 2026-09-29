import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";

// Patient self-registration: creates the login and the patient profile together.
export default function Register() {
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    date_of_birth: "",
    email: "",
    phone: "",
    password: "",
  });
  const [error, setError] = useState("");
  const { register } = useAuth();
  const navigate = useNavigate();

  const field = (name) => ({ value: form[name], onChange: (e) => setForm({ ...form, [name]: e.target.value }) });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      await register({ ...form, phone: form.phone || null });
      navigate("/dashboard");
    } catch (err) {
      setError(getErrorMessage(err, "Registration failed"));
    }
  };

  return (
    <form className="card stack" onSubmit={handleSubmit}>
      <h2>Create your patient account</h2>
      <Alert>{error}</Alert>
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
      <label>
        Date of birth
        <input type="date" {...field("date_of_birth")} required />
      </label>
      <label>
        Email
        <input type="email" {...field("email")} required />
      </label>
      <label>
        Phone (optional)
        <input {...field("phone")} />
      </label>
      <label>
        Password (min 8 characters)
        <input type="password" minLength={8} {...field("password")} required />
      </label>
      <button type="submit">Register</button>
      <p className="small muted">
        Already registered? <Link to="/login">Log in</Link>
      </p>
    </form>
  );
}
