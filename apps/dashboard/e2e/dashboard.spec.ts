import { test, expect } from "@playwright/test";

// The dashboard renders from embedded demo data (no backend needed), so these run against
// the static file alone.

test("risk dashboard renders with the proactive interrupt", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Risk Dashboard" })).toBeVisible();
  await expect(page.getByText(/deploy will fail/i)).toBeVisible();
  await expect(page.getByText("release v2.4.0 → billing")).toBeVisible();
  // KPI: 9 tracked entities from the demo scenario.
  await expect(page.getByText("TRACKED ENTITIES")).toBeVisible();
});

test("navigates to the graph explorer", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Graph Explorer" }).click();
  await expect(page.getByRole("heading", { name: /Graph .* Explorer/ })).toBeVisible();
});

test("search surfaces a matching entity", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Search" }).click();
  await page.getByPlaceholder(/Search entities/i).fill("billing");
  await expect(page.getByText("billing-service")).toBeVisible();
});

test("notification feed shows the slack interrupt", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Notification Feed" }).click();
  await expect(page.getByText("SLACK")).toBeVisible();
  await expect(page.getByText(/oncall/)).toBeVisible();
});
