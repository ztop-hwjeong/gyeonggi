import { expect, test } from "@playwright/test";

test("이벤트를 등록하고 수정한 뒤 삭제한다", async ({ page }) => {
  let item: Record<string, unknown> | null = null;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api", "");
    if (path === "/tags")
      return route.fulfill({
        json: [{ id: "tag", name: "교권", material_count: 0, folder_ids: [] }],
      });
    if (path === "/tag-folders")
      return route.fulfill({
        json: [{ id: "folder", name: "정책", material_count: 0 }],
      });
    if (path === "/tags/unfiled/summary")
      return route.fulfill({ json: { tag_count: 1, material_count: 0 } });
    if (path === "/events" && request.method() === "GET")
      return route.fulfill({ json: item ? [item] : [] });
    if (path === "/events" && request.method() === "POST") {
      item = {
        id: "event",
        version: 1,
        created_at: "2026-10-26T01:00:00Z",
        updated_at: "2026-10-26T01:00:00Z",
        targets: [{ kind: "tag", id: "tag", name: "교권" }],
        ...request.postDataJSON(),
      };
      return route.fulfill({ status: 201, json: item });
    }
    if (path === "/events/event" && request.method() === "PUT") {
      item = { ...item, ...request.postDataJSON(), version: 2 };
      return route.fulfill({ json: item });
    }
    if (path === "/events/event" && request.method() === "DELETE") {
      item = null;
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ status: 500, json: { detail: path } });
  });
  await page.goto("/events");
  await page.getByLabel("이름").fill("정책 발표");
  await page.getByLabel("기준 시각").fill("2026-10-26T10:30");
  await page.getByRole("button", { name: "미분류 태그 펼치기" }).click();
  await page.screenshot({
    path: "../.tmp/frontend/event-folder-tree.png",
    fullPage: true,
  });
  await page.getByRole("checkbox", { name: "미분류 태그 교권 선택" }).check();
  await page.getByRole("button", { name: "등록", exact: true }).click();
  await expect(page.getByText("정책 발표")).toBeVisible();
  await page.getByRole("button", { name: "수정" }).click();
  await page.getByLabel("이름").fill("정책 발표 수정");
  await page.getByRole("button", { name: "수정 저장" }).click();
  await expect(page.getByText("정책 발표 수정")).toBeVisible();
  await page.getByRole("button", { name: "삭제" }).click();
  await expect(page.getByText("등록한 이벤트가 없어요")).toBeVisible();
});
