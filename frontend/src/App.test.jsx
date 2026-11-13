import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";

const data = {
  "/auth/login": { access_token: "tok" },
  "/topics": [{ id: 1, slug: "umwelt", name_de: "Umwelt", name_ko: "환경", level: "A2" }],
  "/topics/1/passages": [{ id: 7, topic_id: 1, title: "Der Wald", level: "A2" }],
  "/passages/7": {
    id: 7, topic_id: 1, title: "Der Wald", level: "A2",
    sentences: [
      { id: 1, position: 0, text_de: "Der Wald ist grün.", text_ko: "숲은 푸르다." },
      { id: 2, position: 1, text_de: "Ich gehe spazieren.", text_ko: "나는 산책한다." },
    ],
  },
};

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url, opts = {}) => {
    const path = new URL(url).pathname;
    if (path !== "/auth/login" && opts.headers?.Authorization !== "Bearer tok") {
      return { ok: false, status: 401, json: async () => ({}) };
    }
    return { ok: true, status: 200, json: async () => data[path] };
  }));
});
afterEach(() => vi.unstubAllGlobals());

test("redirects to login when logged out", () => {
  render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "Log in" })).toBeInTheDocument();
});

test("login, topic, passage, per-sentence translation toggle", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={["/login"]}><App /></MemoryRouter>);

  await user.type(screen.getByLabelText(/email/i), "a@example.com");
  await user.type(screen.getByLabelText(/password/i), "password123");
  await user.click(screen.getByRole("button", { name: "Log in" }));

  await user.click(await screen.findByRole("link", { name: /Umwelt/ }));
  await user.click(await screen.findByRole("link", { name: /Der Wald/ }));

  const sentences = await screen.findAllByTestId("sentence");
  expect(sentences).toHaveLength(2);
  expect(screen.getByText("Der Wald ist grün.")).toBeInTheDocument();
  expect(screen.queryByText("숲은 푸르다.")).not.toBeInTheDocument();

  const buttons = screen.getAllByRole("button", { name: "Show translation" });
  await user.click(buttons[0]);
  expect(screen.getByText("숲은 푸르다.")).toBeInTheDocument();
  expect(screen.queryByText("나는 산책한다.")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Hide translation" }));
  await waitFor(() => expect(screen.queryByText("숲은 푸르다.")).not.toBeInTheDocument());
});

test("click a word to collect it; vocabulary shows entry and lemma override", async () => {
  const user = userEvent.setup();
  localStorage.setItem("dt_token", "tok");
  const disc = { id: 5, lemma: "gehen", word_lemma: "gehen", lemma_override: null, surface_form: "gehe",
    sentence_de: "Ich gehe spazieren.", passage_title: "Der Wald", created_at: "2026-01-02T00:00:00Z" };
  const calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url, opts = {}) => {
    const path = new URL(url).pathname;
    calls.push([opts.method ?? "GET", path, opts.body]);
    if (path === "/passages/7") return { ok: true, status: 200, json: async () => ({ id: 7, title: "Der Wald",
      sentences: [{ id: 2, text_de: "Ich gehe spazieren.", text_ko: "x", tokens: [
        { id: 11, position: 0, surface: "Ich", word_id: null }, { id: 12, position: 1, surface: "gehe", word_id: 3 }] }] }) };
    if (path === "/discoveries" && opts.method === "POST") return { ok: true, status: 201, json: async () => disc };
    if (path === "/discoveries" ) return { ok: true, status: 200, json: async () => [disc] };
    if (path === "/discoveries/5") return { ok: true, status: 200, json: async () => ({ ...disc, lemma: "laufen", lemma_override: "laufen" }) };
    return { ok: false, status: 404, json: async () => ({}) };
  }));
  render(<MemoryRouter initialEntries={["/passages/7"]}><App /></MemoryRouter>);
  expect(screen.queryByRole("button", { name: "Ich" })).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "gehe" }));
  expect(calls).toContainEqual(["POST", "/discoveries", JSON.stringify({ token_id: 12 })]);

  await user.click(screen.getByRole("link", { name: "Vocabulary" }));
  const entry = await screen.findByTestId("entry");
  expect(entry).toHaveTextContent("gehen");
  expect(entry).toHaveTextContent("gehe");
  expect(entry).toHaveTextContent("Ich gehe spazieren.");
  expect(entry).toHaveTextContent("Der Wald");
  await user.click(screen.getByRole("button", { name: "Edit lemma" }));
  await user.type(screen.getByLabelText("Lemma"), "laufen");
  await user.click(screen.getByRole("button", { name: "Save lemma" }));
  await waitFor(() => expect(screen.getByTestId("entry")).toHaveTextContent("laufen"));
  expect(calls).toContainEqual(["PATCH", "/discoveries/5", JSON.stringify({ lemma_override: "laufen" })]);
});
