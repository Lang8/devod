import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";

const base = {
  id: 5, topic_id: 1, title: "Berlin", level: "A2",
  sentences: [{ id: 1, text_de: "Berlin ist groß.", text_ko: "베를린은 크다.", tokens: [] }],
  source_title: "Berlin", author: "Wikipedia-Autoren",
  source_url: "https://de.wikipedia.org/wiki/Berlin", license: "CC BY-SA 4.0", adapted: false,
};
let passage;
beforeEach(() => {
  localStorage.setItem("dt_token", "tok");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => passage })));
});
afterEach(() => vi.unstubAllGlobals());

const show = () => render(<MemoryRouter initialEntries={["/passages/5"]}><App /></MemoryRouter>);

test("attribution footer shows title, author, url, license", async () => {
  passage = base;
  show();
  const f = await screen.findByTestId("attribution");
  expect(f).toHaveTextContent("Berlin");
  expect(f).toHaveTextContent("Wikipedia-Autoren");
  expect(f).toHaveTextContent("CC BY-SA 4.0");
  expect(within(f).getByRole("link")).toHaveAttribute("href", base.source_url);
  expect(f).not.toHaveTextContent("adapted");
});

test("adapted passage is marked adapted", async () => {
  passage = { ...base, adapted: true };
  show();
  expect(await screen.findByTestId("attribution")).toHaveTextContent("adapted");
});
