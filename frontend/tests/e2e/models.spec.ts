import { expect, test } from "@playwright/test";

// fmtNum renders with a fixed fraction count; derive expected text instead of
// hard-coding en-US separators.
const num = (value: number, digits: number) =>
  value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

test("creates, updates and deletes a Black-Scholes model", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend",
  );

  page.on("dialog", (dialog) => {
    void dialog.accept();
  });

  await page.goto("/models");
  await page.locator("#model-name").fill("E2E Alpha Model");
  await page.locator("#model-vol").fill("0.2");
  await page.getByRole("button", { name: "Create model" }).click();

  const createdRow = page.getByRole("row").filter({ hasText: "E2E Alpha Model" });
  await expect(createdRow).toBeVisible();
  await expect(createdRow).toContainText("BSModelData_");
  await expect(createdRow).toContainText(num(0.2, 4));

  // The Models page has no inline editor; the update path is PUT /api/models/{id}.
  // Drive it through the request context and verify the UI reflects the merge.
  const modelsResp = await page.request.get("/api/models");
  const models = (await modelsResp.json()) as { id: string; name: string }[];
  const modelId = models.find((m) => m.name === "E2E Alpha Model")?.id;
  expect(modelId).toBeTruthy();

  const updateResp = await page.request.put(`/api/models/${modelId}`, {
    data: {
      name: "E2E Beta Model",
      bs: { spot: 100, vol: 0.35, rate: 0.01, div: 0.0 },
    },
  });
  expect(updateResp.ok()).toBeTruthy();

  await page.reload();
  const updatedRow = page.getByRole("row").filter({ hasText: "E2E Beta Model" });
  await expect(updatedRow).toBeVisible();
  await expect(updatedRow).toContainText("BSModelData_");
  await expect(updatedRow).toContainText(num(0.35, 4));
  await expect(updatedRow).toContainText(num(0.01, 4));
  await expect(page.getByRole("row").filter({ hasText: "E2E Alpha Model" })).toHaveCount(0);

  await updatedRow.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("row").filter({ hasText: "E2E Beta Model" })).toHaveCount(0);
});

test("rejects a Dupire surface whose vols do not match spots x times", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend",
  );

  await page.goto("/models");
  await page.locator("#model-kind").selectOption("DupireModelData_");
  await page.locator("#model-name").fill("E2E Broken Dupire");
  // Default vols are a 3x3 matrix against three spot strikes; shrinking the
  // times axis to two entries makes the surface non-rectangular.
  await page.locator("#dupire-times").fill("0.25, 0.5");
  await page.getByRole("button", { name: "Create model" }).click();

  const banner = page.locator("div.error");
  await expect(banner).toContainText("422");
  await expect(banner).toContainText(
    "Dupire vols must be a rectangular matrix matching spots x times",
  );
  await expect(page.getByRole("row").filter({ hasText: "E2E Broken Dupire" })).toHaveCount(0);
});

test("model delete is guarded while a trade references it", async ({ page }) => {
  test.skip(
    process.env.DAL_PLAYWRIGHT_TEST_BACKEND !== "1",
    "Only applies to the explicit Playwright test backend",
  );

  const productResp = await page.request.post("/api/products", {
    data: {
      name: "E2E ModelGuard Product",
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
      name: "E2E Guarded Model",
      kind: "BSModelData_",
      bs: { spot: 100, vol: 0.2, rate: 0.0, div: 0.0 },
    },
  });
  expect(modelResp.status()).toBe(201);
  const model = (await modelResp.json()) as { id: string };

  const tradeResp = await page.request.post("/api/trades", {
    data: {
      name: "E2E ModelGuard Trade",
      book: "EQ-EXOTICS",
      counterparty: "",
      notional: 1,
      quantity: 1,
      product_id: product.id,
      model_id: model.id,
    },
  });
  expect(tradeResp.status()).toBe(201);
  const trade = (await tradeResp.json()) as { id: string };

  page.on("dialog", (dialog) => {
    void dialog.accept();
  });

  // Deleting the referenced model is rejected with a 409 naming the trade.
  await page.goto("/models");
  const modelRow = page.getByRole("row").filter({ hasText: "E2E Guarded Model" });
  await expect(modelRow).toBeVisible();
  await modelRow.getByRole("button", { name: "Delete" }).click();

  const banner = page.locator("div.error");
  await expect(banner).toContainText("409");
  await expect(banner).toContainText("Cannot delete model");
  await expect(banner).toContainText(`still referenced by trade ${trade.id}`);
  await expect(modelRow).toBeVisible();

  // Once the referencing trade is gone the delete succeeds.
  const deleteResp = await page.request.delete(`/api/trades/${trade.id}`);
  expect(deleteResp.status()).toBe(204);
  await modelRow.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("row").filter({ hasText: "E2E Guarded Model" })).toHaveCount(0);
});
