import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getTopicPassages } from "../api.js";

export default function TopicPassages() {
  const { topicId } = useParams();
  const [passages, setPassages] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getTopicPassages(topicId).then(setPassages).catch(() => setError("Failed to load passages"));
  }, [topicId]);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!passages) return <p>Loading…</p>;
  return (
    <>
      <h1>Passages</h1>
      <ul>
        {passages.map((p) => (
          <li key={p.id}>
            <Link to={`/passages/${p.id}`}>{p.title}</Link> · {p.level}
          </li>
        ))}
      </ul>
    </>
  );
}
