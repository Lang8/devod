import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";

const questions = [
  { word_id: 1, discovery_id: 1, question_type: "de_ko", prompt: "gehen" },
  { word_id: 1, discovery_id: 1, question_type: "mcq", prompt: "gehen", choices: ["가다", "집"] },
  { word_id: 2, discovery_id: 2, question_type: "cloze", prompt: "Das _____ ist groß.", hint: "집은 크다." },
];
let calls;

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("dt_token", "tok");
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url, opts = {}) => {
    const u = new URL(url);
    calls.push([opts.method ?? "GET", u.pathname + u.search, opts.body]);
    let body = [];
    if (u.pathname === "/topics") body = [{ id: 3, name_de: "Umwelt", name_ko: "환경", level: "A2" }];
    if (u.pathname === "/quiz/questions") body = questions;
    if (u.pathname === "/quiz/answer") {
      const a = JSON.parse(opts.body).answer;
      body = { correct: a === "가다" || a === "Haus", expected: "가다" };
    }
    return { ok: true, status: 200, json: async () => body };
  }));
});
afterEach(() => vi.unstubAllGlobals());

test("quiz: topic filter, answers recorded via API, score shown", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={["/quiz"]}><App /></MemoryRouter>);
  await screen.findByRole("option", { name: "Umwelt" });
  await user.selectOptions(screen.getByLabelText("Topic"), "3");
  await user.click(screen.getByRole("button", { name: "Start quiz" }));
  expect(calls.some(([, p]) => p.startsWith("/quiz/questions") && p.includes("topic_id=3"))).toBe(true);

  await user.type(await screen.findByLabelText("Answer"), "가다");
  await user.click(screen.getByRole("button", { name: "Check" }));
  expect(await screen.findByText("Correct!")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next" }));

  await user.click(await screen.findByRole("button", { name: "집" }));
  expect(await screen.findByText(/Wrong — expected: 가다/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next" }));

  expect(screen.getByText("Das _____ ist groß.")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Answer"), "Haus");
  await user.click(screen.getByRole("button", { name: "Check" }));
  await user.click(await screen.findByRole("button", { name: "Next" }));

  expect(screen.getByTestId("score")).toHaveTextContent("Score: 2 / 3");
  expect(calls.filter(([m, p]) => m === "POST" && p === "/quiz/answer")).toHaveLength(3);
});
