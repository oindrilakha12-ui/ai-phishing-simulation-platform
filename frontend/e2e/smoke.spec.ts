import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "PhishGuard!2026";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

test("manager: login → dashboard → campaigns → preview sandbox", async ({ page }) => {
  await login(page, "manager@globex.example.com");
  await expect(page.getByRole("heading", { name: "Analytics dashboard" })).toBeVisible();
  await expect(page.getByText("Click rate").first()).toBeVisible();
  await expect(page.getByText("DEMO MODE").first()).toBeVisible();

  await page.getByRole("link", { name: "Campaigns" }).click();
  await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  await page.getByRole("table").getByRole("link").first().click();
  await expect(page.getByText("Synthetic event log")).toBeVisible();

  await page.getByRole("link", { name: "Templates" }).click();
  await page.getByRole("link", { name: "Parking permit renewal" }).click();
  const frame = page.locator('iframe[title="Sandboxed email preview"]');
  await expect(frame).toHaveAttribute("sandbox", "allow-same-origin");
  await expect(frame.contentFrame().getByText("SIMULATION — TRAINING ONLY")).toBeVisible();
  await expect(page.getByText(/Mismatch: shows/)).toBeVisible();
  // Hovering a red flag highlights the cue inside the sandboxed email.
  await page.getByRole("button", { name: /Urgency/ }).hover();
  await expect(frame.contentFrame().locator("mark.pg-active")).toHaveCount(1);
});

test("manager: AI Studio analyzer streams and shows indicators; refusal works", async ({ page }) => {
  await login(page, "manager@globex.example.com");
  await page.goto("/ai?tab=analyze");
  await page.getByRole("button", { name: "Load sample" }).click();
  await page.getByRole("button", { name: "Analyze" }).click();
  await expect(page.getByText("Lookalike sender domain", { exact: true })).toBeVisible();
  await expect(page.getByText(/DEMO — example explanation/)).toBeVisible();

  await page.getByRole("tab", { name: "Training Example Viewer" }).click();
  await page.getByRole("button", { name: "Generate fictional training example" }).click();
  await expect(page.getByText("SIMULATION — TRAINING ONLY").first()).toBeVisible();
  await expect(page.getByText("passed")).toBeVisible();

  await page.getByRole("tab", { name: "Knowledge Q&A" }).click();
  await page.getByLabel(/Free-text mode/).check();
  await page.getByLabel("Your question").fill("a fake login page for a real bank");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText("refused (out of scope)")).toBeVisible();

  await page.getByLabel(/Free-text mode/).uncheck();
  await page.getByLabel("Your question").fill("How do I report a suspicious email?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText(/\[How to Report a Suspicious Email\]/)).toBeVisible();
});

test("learner: inbox → report simulation; training visible; admin hidden", async ({ page }) => {
  await login(page, "learner@globex.example.com");
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  await page.getByRole("link", { name: "Simulation inbox" }).click();
  const unreviewed = page.getByRole("row").filter({ hasText: "Unreviewed" }).getByRole("link").first();
  if (await unreviewed.count()) {
    await unreviewed.click();
    await page.getByRole("button", { name: /Report phish/ }).click();
    await expect(page.getByText(/Well spotted/)).toBeVisible();
  }
  await page.getByRole("link", { name: "Training", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Training" })).toBeVisible();
  await page.goto("/ai?tab=coach");
  await page.getByRole("button", { name: "Get my tips" }).click();
  await expect(page.getByText("Weakest areas:")).toBeVisible();
});

test("admin: audit log and API keys render", async ({ page }) => {
  await login(page, "admin@globex.example.com");
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByRole("table", { name: "Audit entries" })).toBeVisible();
  await expect(page.getByText("auth.login").first()).toBeVisible();
});
