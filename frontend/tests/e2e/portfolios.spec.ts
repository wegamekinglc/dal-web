import { expect, test } from "@playwright/test";

// The app formats numbers via toLocaleString(undefined, ...); derive expected
// text instead of hard-coding en-US separators.
const money = (value: number) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);

const NOTIONAL = 1_500_000;
// Canned backend prices every trade at unit PV 8.0, scaled by notional x quantity.
const TOTAL_PV_TEXT = money(8 * NOTIONAL);
const PATH_COUNT_TEXT = (2048).toLocaleString();

// valuation.spec.ts runs on a parallel worker against the same in-memory
// store and asserts on the NEWEST valuation run (`.first()`), snapshotted
// right after its own 1024-path run completes. A run of ours created between
// its run and its /valuations snapshot would take that slot. Its run requires
// a trade named "E2E trade" created through the UI first, so:
//   - no "E2E trade" trade yet -> its run cannot exist; ours will be older;
//   - otherwise wait until its 1024-path run has settled and its snapshot
//     window (a few seconds after completion) has closed.
async function dodgeValuationSpecWindow(page: import("@playwright/test").Page) {
  const tradesResp = await page.request.get("/api/trades");
  const trades = (await tradesResp.json()) as { name: string }[];
  if (!trades.some((t) => t.name === "E2E trade")) return;

  const listRuns = async () => {
    const resp = await page.request.get("/api/valuations");
    return (await resp.json()) as {
      status: string;
      config: { num_paths: number };
    }[];
  };
  await expect
    .poll(
      async () =>
        (await listRuns()).find((r) => r.config.num_paths === 1024)?.status,
      { timeout: 60_000 }
    )
    .toBe("completed");
  await page.waitForTimeout(5_000);
}

async function seedTrade(page: import("@playwright/test").Page) {
  const productResp = await page.request.post("/api/products", {
    data: {
      name: "E2E PF Product",
      description: "",
      template: null,
      rows: [
        { date_kind: "label", label: "STRIKE", event: "120.00" },
        {
          date_kind: "date",
          date: "2025-09-15",
          event: "call pays MAX(spot() - STRIKE, 0.0)",
        },
      ],
    },
  });
  expect(productResp.status()).toBe(201);
  const product = (await productResp.json()) as { id: string };

  const modelResp = await page.request.post("/api/models", {
    data: {
      name: "E2E PF Model",
      kind: "BSModelData_",
      bs: { spot: 100, vol: 0.2, rate: 0.0, div: 0.0 },
    },
  });
  expect(modelResp.status()).toBe(201);
  const model = (await modelResp.json()) as { id: string };

  const tradeResp = await page.request.post("/api/trades", {
    data: {
      name: "E2E PF Trade",
      book: "EQ-EXOTICS",
      counterparty: "",
      notional: NOTIONAL,
      quantity: 1,
      product_id: product.id,
      model_id: model.id,
    },
  });
  expect(tradeResp.status()).toBe(201);
}

test("portfolio lifecycle: create, add trade, price, remove trade, delete", async ({
  page,
}) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend"
  );

  await seedTrade(page);

  // Deletion and removal go through window.confirm; accept every dialog.
  page.on("dialog", (dialog) => {
    void dialog.accept();
  });

  await page.goto("/portfolios");
  await expect(page.getByRole("heading", { name: "Portfolios" })).toBeVisible();

  // Create the portfolio via the Books panel form.
  await page.getByRole("textbox").fill("E2E Portfolio Alpha");
  await page.getByRole("button", { name: "Create" }).click();
  const bookRow = page.getByRole("row").filter({ hasText: "E2E Portfolio Alpha" });
  await expect(bookRow).toBeVisible();
  await expect(bookRow.locator("td").nth(2)).toHaveText("0");

  // Open it and add the seeded trade through the picker.
  await bookRow.getByRole("button", { name: "Open" }).click();
  await expect(
    page.getByRole("heading", { name: "E2E Portfolio Alpha", exact: true })
  ).toBeVisible();
  await page
    .locator("select")
    .filter({ hasText: "pick a trade" })
    .selectOption({ label: "E2E PF Trade" });
  await page.getByRole("button", { name: "Add trade" }).click();

  const memberRow = page.getByRole("row").filter({ hasText: "E2E PF Trade" });
  await expect(memberRow).toBeVisible();
  await expect(memberRow).toContainText(money(NOTIONAL));
  await expect(bookRow.locator("td").nth(2)).toHaveText("1");

  // Price the portfolio through its ValuationPanel; canned PV is 8 x notional.
  await expect(
    page.getByRole("heading", { name: "Price portfolio: E2E Portfolio Alpha" })
  ).toBeVisible();
  await page.getByLabel("Number of paths").fill("2048");
  await dodgeValuationSpecWindow(page);
  await page.getByRole("button", { name: "Run valuation" }).click();
  await expect(page.getByText("Total PV")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(TOTAL_PV_TEXT)).toBeVisible();
  await expect(page.getByRole("heading", { name: "d_spot" })).toBeVisible();

  // The settled run lands on /valuations with target kind portfolio.
  await page.goto("/valuations");
  const runRow = page
    .getByRole("row")
    .filter({ hasText: "portfolio" })
    .filter({ hasText: TOTAL_PV_TEXT });
  await expect(runRow).toContainText("completed");
  await expect(runRow).toContainText("canned-dal");
  await expect(runRow).toContainText(PATH_COUNT_TEXT);

  // Remove the trade (confirmation flow) and the member table empties.
  await page.goto("/portfolios");
  await page
    .getByRole("row")
    .filter({ hasText: "E2E Portfolio Alpha" })
    .getByRole("button", { name: "Open" })
    .click();
  await page
    .getByRole("row")
    .filter({ hasText: "E2E PF Trade" })
    .getByRole("button", { name: "Remove" })
    .click();
  await expect(
    page.getByRole("row").filter({ hasText: "E2E PF Trade" })
  ).toHaveCount(0);
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "E2E Portfolio Alpha" })
      .locator("td")
      .nth(2)
  ).toHaveText("0");

  // Delete the portfolio (confirmation flow); the selector resets.
  await page
    .getByRole("row")
    .filter({ hasText: "E2E Portfolio Alpha" })
    .getByRole("button", { name: "Delete" })
    .click();
  await expect(
    page.getByRole("row").filter({ hasText: "E2E Portfolio Alpha" })
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Select a portfolio" })
  ).toBeVisible();
});
