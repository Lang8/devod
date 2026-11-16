import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { createDiscovery, getPassage } from "../api.js";

function Attribution({ passage: p }) {
  if (!p.source_title && !p.author && !p.source_url && !p.license) return null;
  return (
    <footer className="attribution" data-testid="attribution">
      {p.source_title && <span>{p.source_title}</span>}
      {p.author && <span>{" · "}{p.author}</span>}
      {p.source_url && (
        <span>{" · "}<a href={p.source_url} rel="noopener noreferrer">{p.source_url}</a></span>
      )}
      {p.license && <span>{" · "}{p.license}</span>}
      {p.adapted && <span>{" · "}<em>adapted</em></span>}
    </footer>
  );
}

export default function PassageView() {
  const { passageId } = useParams();
  const [passage, setPassage] = useState(null);
  const [shown, setShown] = useState(() => new Set());
  const [error, setError] = useState("");
  const [collected, setCollected] = useState(() => new Set());

  useEffect(() => {
    getPassage(passageId).then(setPassage).catch(() => setError("Failed to load passage"));
  }, [passageId]);

  const toggle = (id) =>
    setShown((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const collect = async (tokenId) => {
    try {
      await createDiscovery(tokenId);
      setCollected((prev) => new Set(prev).add(tokenId));
    } catch {
      setError("Failed to save word");
    }
  };

  if (error) return <p role="alert" className="error">{error}</p>;
  if (!passage) return <p>Loading…</p>;
  return (
    <>
      <h1>{passage.title}</h1>
      {passage.sentences.map((s) => (
        <div className="sentence" key={s.id} data-testid="sentence">
          {s.tokens?.length ? (
            <p lang="de">
              {s.tokens.map((t) =>
                t.word_id ? (
                  <button key={t.id} className={"word" + (collected.has(t.id) ? " collected" : "")}
                    title="Add to vocabulary" onClick={() => collect(t.id)}>
                    {t.surface}
                  </button>
                ) : (
                  <span key={t.id}>{t.surface}</span>
                ),
              )}
            </p>
          ) : (
            <p lang="de">{s.text_de}</p>
          )}
          <button aria-expanded={shown.has(s.id)} onClick={() => toggle(s.id)}>
            {shown.has(s.id) ? "Hide translation" : "Show translation"}
          </button>
          {shown.has(s.id) && <p className="ko" lang="ko">{s.text_ko}</p>}
        </div>
      ))}
      <Attribution passage={passage} />
    </>
  );
}
