import { expect, test } from "@playwright/test";

test("register → login → open passage → click word → vocabulary → quiz", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const password = "correct-horse-1";

  // register (auto-logs in), then log out and log in again explicitly
  await page.goto("/login");
  await page.getByRole("button", { name: "Need an account?" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Register" }).click();
  await expect(page.getByRole("heading", { name: "Topics" })).toBeVisible();
  await page.getByRole("button", { name: "Logout" }).click();

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Topics" })).toBeVisible();

  // open passage
  await page.getByRole("link", { name: /Umwelt/ }).click();
  await page.getByRole("link", { name: "Müll trennen" }).click();
  await expect(page.getByRole("heading", { name: "Müll trennen" })).toBeVisible();

  // click a word
  await page.getByRole("button", { name: "Müll", exact: true }).click();
  await expect(page.locator("button.word.collected")).toHaveCount(1);

  // see it in vocabulary
  await page.getByRole("link", { name: "Vocabulary" }).click();
  const entry = page.getByTestId("entry");
  await expect(entry).toHaveCount(1);
  await expect(entry).toContainText("Müll");
  await expect(entry).toContainText("Der Müll schadet der Umwelt.");

  // complete a quiz (German → Korean only, deterministic)
  await page.getByRole("link", { name: "Quiz" }).click();
  for (const label of ["Korean → German", "Multiple choice", "Cloze"]) {
    await page.getByLabel(label).uncheck();
  }
  await page.getByRole("button", { name: "Start quiz" }).click();
  // the quiz repeats the single collected word up to the question count; answer every question
  const progress = page.getByText(/^Question \d+ \/ \d+$/);
  await expect(progress).toBeVisible();
  const total = Number((await progress.textContent()).split("/")[1]);
  expect(total).toBeGreaterThan(0);
  for (let i = 0; i < total; i++) {
    await expect(page.getByText(`Question ${i + 1} / ${total}`)).toBeVisible();
    await page.getByLabel("Answer").fill("쓰레기");
    await page.getByRole("button", { name: "Check" }).click();
    await expect(page.getByRole("status")).toHaveText("Correct!");
    await page.getByRole("button", { name: "Next" }).click();
  }
  await expect(page.getByTestId("score")).toHaveText(`Score: ${total} / ${total}`);
});
