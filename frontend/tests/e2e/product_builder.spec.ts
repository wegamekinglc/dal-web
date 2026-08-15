import { expect, test } from "@playwright/test";

// The builder toolbar renders one ghost button per template, labelled with the
// template name from GET /api/products/templates.
const TEMPLATES = [
  { name: "European Call", rows: 2 },
  { name: "Up-and-Out Call", rows: 5 },
  { name: "Snowball", rows: 7 },
];

test("loads every builder template into the editor", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend"
  );

  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "Product Builder" })).toBeVisible();

  for (const template of TEMPLATES) {
    await page.getByRole("button", { name: template.name }).click();
    await expect(page.locator("#product-name")).toHaveValue(template.name);
    await expect(page.getByPlaceholder(/event script/)).toHaveCount(
      template.rows
    );
  }
});

test("debugs, saves and reloads a scripted product", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend"
  );

  await page.goto("/products");
  await page.getByRole("button", { name: "European Call" }).click();
  await page.locator("#product-name").fill("E2E Builder Roundtrip");

  // Render the rows through the canned Product_New / Product_Debug dump.
  await page.getByRole("button", { name: "Debug (DAL)" }).click();
  const debug = page.locator("pre.debug");
  await expect(debug).toContainText("STRIKE");
  await expect(debug).toContainText("call pays MAX(spot() - STRIKE, 0.0)");

  await page.getByRole("button", { name: "Save product" }).click();
  const savedRow = page
    .getByRole("row")
    .filter({ hasText: "E2E Builder Roundtrip" });
  await expect(savedRow).toBeVisible();
  // Name / description / # rows columns.
  await expect(savedRow.locator("td").nth(2)).toHaveText("2");

  // Dirty the editor with a different template, then load the saved product
  // back: the schedule must round-trip exactly.
  await page.getByRole("button", { name: "Snowball" }).click();
  await expect(page.getByPlaceholder(/event script/)).toHaveCount(7);

  await savedRow.getByRole("button", { name: "Load" }).click();
  await expect(page.locator("#product-name")).toHaveValue(
    "E2E Builder Roundtrip"
  );
  await expect(page.getByPlaceholder(/event script/)).toHaveCount(2);
  await expect(page.getByPlaceholder(/STRIKE or START/)).toHaveValue("STRIKE");
  await expect(page.getByPlaceholder(/event script/).first()).toHaveValue(
    "120.00"
  );
  await expect(page.getByPlaceholder(/event script/).nth(1)).toHaveValue(
    "call pays MAX(spot() - STRIKE, 0.0)"
  );
  await expect(page.locator('input[type="date"]')).toHaveValue("2025-09-15");
});
