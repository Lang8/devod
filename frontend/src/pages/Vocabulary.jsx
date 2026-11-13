import { useEffect, useState } from "react";
import { getDiscoveries, patchDiscovery } from "../api.js";

function Entry({ d, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(d.lemma_override ?? "");
  const save = async () => {
    onSaved(await patchDiscovery(d.id, value.trim() || null));
    setEditing(false);
  };
  return (
    <li className="entry" data-testid="entry">
      <strong className="lemma">{d.lemma}</strong> <em lang="de">{d.surface_form}</em>
      <p lang="de">{d.sentence_de}</p>
      <small>{d.passage_title} · {new Date(d.created_at).toLocaleDateString()}</small>
      {editing ? (
        <span>
          <label>Lemma <input value={value} onChange={(e) => setValue(e.target.value)} /></label>
          <button onClick={save}>Save lemma</button>
        </span>
      ) : (
        <button onClick={() => setEditing(true)}>Edit lemma</button>
      )}
    </li>
  );
}

export default function Vocabulary() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getDiscoveries().then(setItems).catch(() => setError("Failed to load vocabulary"));
  }, []);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!items) return <p>Loading…</p>;
  return (
    <>
      <h1>Vocabulary</h1>
      {items.length === 0 && <p>No words collected yet.</p>}
      <ul>
        {items.map((d) => (
          <Entry key={d.id} d={d} onSaved={(n) => setItems((xs) => xs.map((x) => (x.id === n.id ? n : x)))} />
        ))}
      </ul>
    </>
  );
}
