const BASE = import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const KEY = "dt_token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY));

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (auth && getToken()) headers.Authorization = `Bearer ${getToken()}`;
  const res = await fetch(BASE + path, { method, headers, body: body && JSON.stringify(body) });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const register = (email, password) =>
  request("/auth/register", { method: "POST", body: { email, password }, auth: false });
export const login = (email, password) =>
  request("/auth/login", { method: "POST", body: { email, password }, auth: false });
export const getTopics = () => request("/topics");
export const getTopicPassages = (id) => request(`/topics/${id}/passages`);
export const getPassage = (id) => request(`/passages/${id}`);
export const createDiscovery = (token_id) => request("/discoveries", { method: "POST", body: { token_id } });
export const getDiscoveries = () => request("/discoveries");
export const patchDiscovery = (id, lemma_override) =>
  request(`/discoveries/${id}`, { method: "PATCH", body: { lemma_override } });
export const getQuizQuestions = ({ topicId, types, count = 10 }) => {
  const p = new URLSearchParams({ types: types.join(","), count: String(count) });
  if (topicId) p.set("topic_id", topicId);
  return request(`/quiz/questions?${p}`);
};
export const submitQuizAnswer = (body) => request("/quiz/answer", { method: "POST", body });
