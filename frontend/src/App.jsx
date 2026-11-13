import { useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { getToken, setToken } from "./api.js";
import Login from "./pages/Login.jsx";
import Topics from "./pages/Topics.jsx";
import TopicPassages from "./pages/TopicPassages.jsx";
import Vocabulary from "./pages/Vocabulary.jsx";
import PassageView from "./pages/PassageView.jsx";
import Quiz from "./pages/Quiz.jsx";

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const navigate = useNavigate();

  const onLogin = (token) => {
    setToken(token);
    setAuthed(true);
    navigate("/");
  };
  const logout = () => {
    setToken(null);
    setAuthed(false);
    navigate("/login");
  };

  const guard = (el) => (authed ? el : <Navigate to="/login" replace />);

  return (
    <>
      <header>
        <Link to="/">Deutsch Trainer</Link>
        {authed && <Link to="/vocabulary">Vocabulary</Link>}
        {authed && <Link to="/quiz">Quiz</Link>}
        {authed && <button onClick={logout}>Logout</button>}
      </header>
      <main>
        <Routes>
          <Route path="/login" element={<Login onLogin={onLogin} />} />
          <Route path="/" element={guard(<Topics />)} />
          <Route path="/topics/:topicId" element={guard(<TopicPassages />)} />
          <Route path="/passages/:passageId" element={guard(<PassageView />)} />
          <Route path="/vocabulary" element={guard(<Vocabulary />)} />
          <Route path="/quiz" element={guard(<Quiz />)} />
        </Routes>
      </main>
    </>
  );
}
