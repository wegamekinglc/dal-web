import { expect, test, type Page } from "@playwright/test";

// The app formats notionals via toLocaleString(undefined, ...); derive
// expected text instead of hard-coding en-US separators.
const money = (value: number) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);

async function seedProductAndModel(
  page: Page,
  names: { product: string; model: string }
) {
  const productResp = await page.request.post("/api/products", {
    data: {
      name: names.product,
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
      name: names.model,
      kind: "BSModelData_",
      bs: { spot: 100, vol: 0.2, rate: 0.0, div: 0.0 },
    },
  });
  expect(modelResp.status()).toBe(201);
  const model = (await modelResp.json()) as { id: string };

  return { productId: product.id, modelId: model.id };
}

test("creates, updates and deletes a trade", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend"
  );

  await seedProductAndModel(page, {
    product: "E2E Ticket Product",
    model: "E2E Ticket Model",
  });

  // Deletion goes through window.confirm; accept every dialog.
  page.on("dialog", (dialog) => {
    void dialog.accept();
  });

  await page.goto("/trades");
  await page.locator("#trade-name").fill("E2E Ticket Alpha");
  await page.locator("#trade-product").selectOption({ label: "E2E Ticket Product" });
  await page.locator("#trade-model").selectOption({ label: "E2E Ticket Model" });
  await page.locator("#trade-notional").fill("2000000");
  await page.getByRole("button", { name: "Create" }).click();

  const createdRow = page.getByRole("row").filter({ hasText: "E2E Ticket Alpha" });
  await expect(createdRow).toBeVisible();
  await expect(createdRow).toContainText("E2E Ticket Product");
  await expect(createdRow).toContainText("E2E Ticket Model");
  await expect(createdRow).toContainText(money(2_000_000));

  // The Trades page has no inline editor; the update path is PUT /api/trades/{id}.
  // Drive it through the request context and verify the UI reflects the merge.
  const tradesResp = await page.request.get("/api/trades");
  const trades = (await tradesResp.json()) as { id: string; name: string }[];
  const tradeId = trades.find((t) => t.name === "E2E Ticket Alpha")?.id;
  expect(tradeId).toBeTruthy();

  const updateResp = await page.request.put(`/api/trades/${tradeId}`, {
    data: { name: "E2E Ticket Beta", notional: 3_500_000 },
  });
  expect(updateResp.ok()).toBeTruthy();

  await page.reload();
  const renamedRow = page
    .getByRole("row")
    .filter({ hasText: "E2E Ticket Beta" });
  await expect(renamedRow).toBeVisible();
  await expect(renamedRow).toContainText(money(3_500_000));
  // Untouched fields survive the partial update.
  await expect(renamedRow).toContainText("E2E Ticket Product");
  await expect(
    page.getByRole("row").filter({ hasText: "E2E Ticket Alpha" })
  ).toHaveCount(0);

  await renamedRow.getByRole("button", { name: "Delete" }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "E2E Ticket Beta" })
  ).toHaveCount(0);
});

test("product delete is guarded while a trade references it", async ({
  page,
}) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend"
  );

  const { productId, modelId } = await seedProductAndModel(page, {
    product: "E2E Guard Product",
    model: "E2E Guard Model",
  });
  const tradeResp = await page.request.post("/api/trades", {
    data: {
      name: "E2E Guard Trade",
      book: "EQ-EXOTICS",
      counterparty: "",
      notional: 1,
      quantity: 1,
      product_id: productId,
      model_id: modelId,
    },
  });
  expect(tradeResp.status()).toBe(201);
  const trade = (await tradeResp.json()) as { id: string };

  page.on("dialog", (dialog) => {
    void dialog.accept();
  });

  // Deleting the referenced product is rejected with a 409 naming the trade.
  await page.goto("/products");
  const productRow = page
    .getByRole("row")
    .filter({ hasText: "E2E Guard Product" });
  await expect(productRow).toBeVisible();
  await productRow.getByRole("button", { name: "Delete" }).click();

  const banner = page.locator("div.error");
  await expect(banner).toContainText("409");
  await expect(banner).toContainText("Cannot delete product");
  await expect(banner).toContainText(`still referenced by trade ${trade.id}`);
  await expect(productRow).toBeVisible();

  // Remove the referencing trade through its own delete flow.
  await page.goto("/trades");
  const tradeRow = page.getByRole("row").filter({ hasText: "E2E Guard Trade" });
  await tradeRow.getByRole("button", { name: "Delete" }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "E2E Guard Trade" })
  ).toHaveCount(0);

  // The product delete now succeeds.
  await page.goto("/products");
  await page
    .getByRole("row")
    .filter({ hasText: "E2E Guard Product" })
    .getByRole("button", { name: "Delete" })
    .click();
  await expect(
    page.getByRole("row").filter({ hasText: "E2E Guard Product" })
  ).toHaveCount(0);
});
