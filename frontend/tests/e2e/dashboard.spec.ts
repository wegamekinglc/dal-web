import { expect, type Page, test } from "@playwright/test";

// The app formats numbers via toLocaleString(undefined, ...); derive expected
// text instead of hard-coding en-US separators.
const money = (value: number) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);

// valuation.spec.ts runs on a parallel worker against the same in-memory
// store and asserts on the NEWEST valuation run (`.first()`), snapshotted
// right after its own 1024-path run completes. A run of ours created between
// its run and its /valuations snapshot would take that slot. Its run requires
// a trade named "E2E trade" created through the UI first, so:
//   - no "E2E trade" trade yet -> its run cannot exist; ours will be older;
//   - otherwise wait until its 1024-path run has settled and its snapshot
//     window (a few seconds after completion) has closed.
async function dodgeValuationSpecWindow(page: Page) {
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
    .poll(async () => (await listRuns()).find((r) => r.config.num_paths === 1024)?.status, {
      timeout: 60_000,
    })
    .toBe("completed");
  await page.waitForTimeout(5_000);
}

// Seeds product + model + trade via the API, prices the trade, and polls until
// the canned backend settles the run. Returns the valuation id.
async function seedCompletedTradeValuation(
  page: Page,
  tradeName: string,
  notional: number,
): Promise<string> {
  const productResp = await page.request.post("/api/products", {
    data: {
      name: `${tradeName} Product`,
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
      name: `${tradeName} Model`,
      kind: "BSModelData_",
      bs: { spot: 100, vol: 0.2, rate: 0.0, div: 0.0 },
    },
  });
  expect(modelResp.status()).toBe(201);
  const model = (await modelResp.json()) as { id: string };

  const tradeResp = await page.request.post("/api/trades", {
    data: {
      name: tradeName,
      book: "EQ-EXOTICS",
      counterparty: "",
      notional,
      quantity: 1,
      product_id: product.id,
      model_id: model.id,
    },
  });
  expect(tradeResp.status()).toBe(201);
  const trade = (await tradeResp.json()) as { id: string };

  await dodgeValuationSpecWindow(page);
  const valueResp = await page.request.post(`/api/trades/${trade.id}/value`, {
    data: {
      num_paths: 512,
      method: "sobol",
      use_brownian_bridge: false,
      enable_aad: true,
      smooth: 0.01,
      evaluation_date: "2022-09-15",
    },
  });
  expect(valueResp.status()).toBe(200);
  const pending = (await valueResp.json()) as { id: string };
  await expect
    .poll(
      async () => {
        const resp = await page.request.get(`/api/valuations/${pending.id}`);
        return ((await resp.json()) as { status: string }).status;
      },
      { timeout: 15_000 },
    )
    .toBe("completed");
  return pending.id;
}

test("dashboard renders entity counts and recent valuation runs", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend",
  );

  const portfolioResp = await page.request.post("/api/portfolios", {
    data: { name: "E2E Dash Portfolio", description: "" },
  });
  expect(portfolioResp.status()).toBe(201);
  // Canned unit PV is 8.0; notional 777,000 keeps this run's PV unique.
  await seedCompletedTradeValuation(page, "E2E Dash Trade", 777_000);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  // The store is shared across the run, so counts are lower bounds only.
  const cardMetric = async (label: string) => {
    const card = page.locator(".card").filter({
      has: page.getByRole("heading", { name: label, exact: true }),
    });
    return Number(await card.locator(".metric").textContent());
  };
  await expect(async () => {
    expect(await cardMetric("Portfolios")).toBeGreaterThanOrEqual(1);
    expect(await cardMetric("Trades")).toBeGreaterThanOrEqual(1);
    expect(await cardMetric("Valuation Runs")).toBeGreaterThanOrEqual(1);
  }).toPass();

  const runRow = page.getByRole("row").filter({ hasText: money(8 * 777_000) });
  await expect(runRow).toBeVisible();
  await expect(runRow).toContainText("trade");
  await expect(runRow).toContainText("canned-dal (stub)");
});

test("valuations page lists runs, badges status and expands details", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend",
  );

  // Notional 888,000 keeps this run's PV distinct from any sibling test.
  await seedCompletedTradeValuation(page, "E2E Badge Trade", 888_000);

  // The canned backend never produces a failed run on its own (per-trade
  // failures still settle as "completed"), so prepend a synthetic failed run
  // to the real list response for badge/error evidence.
  const failedRun = {
    id: "f".repeat(32),
    target_kind: "trade",
    target_id: "0".repeat(32),
    backend: "canned-dal",
    is_native: false,
    config: {
      num_paths: 128,
      method: "sobol",
      use_brownian_bridge: false,
      enable_aad: false,
      smooth: 0.01,
      evaluation_date: null,
    },
    total_pv: 0,
    total_greeks: {},
    trades: [],
    created_at: "2026-01-02T00:00:00Z",
    status: "failed",
    error_message: "synthetic failure for badge evidence",
  };
  await page.route("**/api/valuations", async (route) => {
    const response = await route.fetch();
    const runs = (await response.json()) as unknown[];
    await route.fulfill({
      response,
      contentType: "application/json",
      body: JSON.stringify([failedRun, ...runs]),
    });
  });

  await page.goto("/valuations");
  await expect(page.getByRole("heading", { name: "Valuation Runs" })).toBeVisible();

  const completedRow = page.getByRole("row").filter({ hasText: money(8 * 888_000) });
  await expect(completedRow).toBeVisible();
  await expect(completedRow).toContainText("trade");
  await expect(completedRow).toContainText("completed");
  await expect(completedRow).toContainText("canned-dal (stub)");

  await completedRow.getByRole("button", { name: "Details" }).click();
  await expect(page.getByRole("heading", { name: "Greeks" })).toBeVisible();
  await expect(page.getByText(/d_spot:/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "E2E Badge Trade", exact: true })).toBeVisible();

  const failedRow = page.getByRole("row").filter({ hasText: "failed" });
  await expect(failedRow).toHaveCount(1);
  await failedRow.getByRole("button", { name: "Details" }).click();
  await expect(page.getByRole("heading", { name: "Error" })).toBeVisible();
  await expect(page.getByText("synthetic failure for badge evidence")).toBeVisible();

  // The dashboard flags the failed run inline in its recent-activity table.
  await page.goto("/");
  await expect(page.getByText("(failed)")).toBeVisible();
});
