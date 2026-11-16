import { expect, test } from "@playwright/test";

// Production smoke: logs in with an EXISTING test account (no signup), opens a passage, clicks a word.
// Credentials come from env (GitHub Secrets in CI). Content is whatever is deployed, so nothing is hardcoded.
const email = process.env.PROD_E2E_EMAIL;
const password = process.env.PROD_E2E_PASSWORD;

// Locally without credentials the spec is skipped; in CI missing credentials are a hard failure
// (the e2e job seeds the account, and the production job only runs when its secrets exist).
if (process.env.CI && (!email || !password)) {
  throw new Error("PROD_E2E_EMAIL / PROD_E2E_PASSWORD must be set in CI");
}
test.skip(!email || !password, "PROD_E2E_EMAIL / PROD_E2E_PASSWORD not set");

test("login → open passage → click word", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Topics" })).toBeVisible({ timeout: 90_000 });

  // first topic -> first passage
  await page.locator('a[href^="/topics/"]').first().click();
  await page.locator('a[href^="/passages/"]').first().click();
  await expect(page.getByTestId("sentence").first()).toBeVisible();

  // click the first word; it becomes collected (re-clicks across runs are idempotent server-side)
  const word = page.locator("button.word").first();
  await expect(word).toBeVisible();
  await word.click();
  await expect(word).toHaveClass(/collected/);
  await expect(page.getByRole("alert")).toHaveCount(0);
});
