import { useEffect, useState } from "react";
import { getQuizQuestions, getTopics, submitQuizAnswer } from "../api.js";

const TYPES = [
  ["de_ko", "German → Korean"],
  ["ko_de", "Korean → German"],
  ["mcq", "Multiple choice"],
  ["cloze", "Cloze"],
];

function Question({ q, onNext }) {
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState(null);
  const submit = async (value) => {
    setResult(await submitQuizAnswer({
      word_id: q.word_id, discovery_id: q.discovery_id, question_type: q.question_type, answer: value,
    }));
  };
  return (
    <section data-testid="question">
      <p lang={q.question_type === "ko_de" ? "ko" : "de"} className="prompt">{q.prompt}</p>
      {q.hint && <small>{q.hint}</small>}
      {q.question_type === "mcq" ? (
        <ul>
          {q.choices.map((c) => (
            <li key={c}><button disabled={!!result} onClick={() => submit(c)}>{c}</button></li>
          ))}
        </ul>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); if (!result) submit(answer); }}>
          <label>Answer <input value={answer} onChange={(e) => setAnswer(e.target.value)} disabled={!!result} /></label>
          <button type="submit" disabled={!!result}>Check</button>
        </form>
      )}
      {result && (
        <>
          <p role="status">{result.correct ? "Correct!" : `Wrong — expected: ${result.expected}`}</p>
          <button onClick={() => onNext(result.correct)}>Next</button>
        </>
      )}
    </section>
  );
}

export default function Quiz() {
  const [topics, setTopics] = useState([]);
  const [topicId, setTopicId] = useState("");
  const [types, setTypes] = useState(TYPES.map(([t]) => t));
  const [questions, setQuestions] = useState(null);
  const [index, setIndex] = useState(0);
  const [score, setScore] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => { getTopics().then(setTopics).catch(() => {}); }, []);

  const toggle = (t) => setTypes((xs) => (xs.includes(t) ? xs.filter((x) => x !== t) : [...xs, t]));
  const start = async () => {
    setError("");
    try {
      setQuestions(await getQuizQuestions({ topicId: topicId || null, types, count: 10 }));
      setIndex(0);
      setScore(0);
    } catch {
      setError("Failed to start quiz");
    }
  };

  if (!questions) {
    return (
      <>
        <h1>Quiz</h1>
        <label>Topic
          <select value={topicId} onChange={(e) => setTopicId(e.target.value)}>
            <option value="">All words</option>
            {topics.map((t) => <option key={t.id} value={t.id}>{t.name_de}</option>)}
          </select>
        </label>
        <fieldset>
          <legend>Question types</legend>
          {TYPES.map(([t, label]) => (
            <label key={t}><input type="checkbox" checked={types.includes(t)} onChange={() => toggle(t)} /> {label}</label>
          ))}
        </fieldset>
        {error && <p role="alert" className="error">{error}</p>}
        <button onClick={start} disabled={types.length === 0}>Start quiz</button>
      </>
    );
  }
  if (questions.length === 0) {
    return <><h1>Quiz</h1><p>No quiz questions available. Collect some words first.</p>
      <button onClick={() => setQuestions(null)}>Back</button></>;
  }
  if (index >= questions.length) {
    return <><h1>Quiz</h1><p data-testid="score">Score: {score} / {questions.length}</p>
      <button onClick={() => setQuestions(null)}>New quiz</button></>;
  }
  return (
    <>
      <h1>Quiz</h1>
      <p>Question {index + 1} / {questions.length}</p>
      <Question key={index} q={questions[index]}
        onNext={(ok) => { setScore((s) => s + (ok ? 1 : 0)); setIndex((i) => i + 1); }} />
    </>
  );
}
