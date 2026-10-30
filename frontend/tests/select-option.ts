import type { Page } from "@playwright/test";

export async function chooseOption(page: Page, label: string, value: string) {
  await page.getByRole("combobox", { name: label, exact: true }).click();
  await page
    .locator(`[role="option"][data-choice-value=${JSON.stringify(value)}]`)
    .click();
}
