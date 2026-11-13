import * as Sentry from "@sentry/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initSentry } from "./sentry.js";

vi.mock("@sentry/react", () => ({ init: vi.fn() }));

describe("initSentry", () => {
  beforeEach(() => Sentry.init.mockClear());
  it("is a no-op without a DSN", () => {
    expect(initSentry("")).toBe(false);
    expect(initSentry(undefined)).toBe(false);
    expect(Sentry.init).not.toHaveBeenCalled();
  });
  it("initialises with a DSN", () => {
    expect(initSentry("https://k@o0.ingest.sentry.io/1")).toBe(true);
    expect(Sentry.init).toHaveBeenCalledOnce();
  });
});
