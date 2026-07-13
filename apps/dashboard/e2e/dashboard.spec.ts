import { test, expect } from "@playwright/test";

// The dashboard renders from embedded demo data (no backend needed). React loads from a CDN,
// so each test first waits for the app to mount (the unique interrupt banner appears).

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Your 15:00 billing deploy will fail/i)).toBeVisible({
    timeout: 20_000,
  });
});

test("risk dashboard shows the interrupt and ranked risks", async ({ page }) => {
  // The KPI label is "Tracked entities" in the DOM (CSS uppercases it), so match
  // case-insensitively.
  await expect(page.getByText(/tracked entities/i)).toBeVisible();
  await expect(page.getByText("INC-2207 payment retries failing")).toBeVisible();
});

test("navigates to the graph explorer", async ({ page }) => {
  await page.getByRole("link", { name: /Graph Explorer/ }).click();
  await expect(page.getByText(/blast-radius view/i)).toBeVisible();
});

test("search surfaces a matching entity", async ({ page }) => {
  await page.getByRole("link", { name: /Search/ }).click();
  await page.getByPlaceholder(/Search entities/i).fill("billing");
  await expect(page.getByText("billing-service")).toBeVisible();
});

test("notification feed shows the slack interrupt", async ({ page }) => {
  await page.getByRole("link", { name: /Notification Feed/ }).click();
  await expect(page.getByText("SLACK")).toBeVisible();
});
