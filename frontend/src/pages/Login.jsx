import { useState } from "react";
import { login, register } from "../api.js";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("login");
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const fn = mode === "login" ? login : register;
      const { access_token } = await fn(email, password);
      onLogin(access_token);
    } catch {
      setError(mode === "login" ? "Login failed" : "Registration failed");
    }
  };

  return (
    <form onSubmit={submit}>
      <h1>{mode === "login" ? "Log in" : "Register"}</h1>
      <p>
        <label>Email <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      </p>
      <p>
        <label>Password <input type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
      </p>
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit">{mode === "login" ? "Log in" : "Register"}</button>{" "}
      <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
        {mode === "login" ? "Need an account?" : "Have an account?"}
      </button>
    </form>
  );
}
