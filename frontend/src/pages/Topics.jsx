import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getTopics } from "../api.js";

export default function Topics() {
  const [topics, setTopics] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getTopics().then(setTopics).catch(() => setError("Failed to load topics"));
  }, []);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!topics) return <p>Loading…</p>;
  return (
    <>
      <h1>Topics</h1>
      <ul>
        {topics.map((t) => (
          <li key={t.id}>
            <Link to={`/topics/${t.id}`}>{t.name_de} ({t.name_ko}) · {t.level}</Link>
          </li>
        ))}
      </ul>
    </>
  );
}
