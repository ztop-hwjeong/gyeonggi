import { expect, test } from "@playwright/test";

const now = "2026-10-26T10:00:00Z";
const ids = {
  policy: "11111111-1111-4111-8111-111111111111",
  ras: "22222222-2222-4222-8222-222222222222",
  detail: "33333333-3333-4333-8333-333333333333",
  other: "44444444-4444-4444-8444-444444444444",
};

test("3단계 폴더에서 태그와 하위 폴더를 함께 보여주고 이동한다", async ({
  page,
}) => {
  let folders = [
    { id: ids.policy, name: "5대 교육정책", parent_id: null },
    { id: ids.ras, name: "RAS", parent_id: ids.policy },
    { id: ids.detail, name: "세부 정책", parent_id: ids.ras },
    { id: ids.other, name: "현안", parent_id: null },
  ].map((item) => ({
    ...item,
    version: 1,
    tag_count: 1,
    material_count: 1,
    created_at: now,
    updated_at: now,
  }));
  let tags = [
    { id: "root-tag", name: "정책 공통", folder_ids: [ids.policy, ids.other] },
    { id: "ras-tag", name: "RAS 태그", folder_ids: [ids.ras] },
    { id: "leaf-tag", name: "세부 태그", folder_ids: [ids.detail] },
  ].map((item) => ({
    ...item,
    version: 1,
    description: "",
    synonyms: [],
    material_count: 1,
    created_at: now,
    updated_at: now,
  }));
  const folderUpdates: Record<string, unknown>[] = [];
  const tagMoves: Record<string, unknown>[] = [];
  const deleted: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api", "");
    if (path === "/tag-folders/tag-moves" && request.method() === "POST") {
      const body = request.postDataJSON();
      tagMoves.push(body);
      tags = tags.map((tag) =>
        tag.id === body.tag_id
          ? {
              ...tag,
              folder_ids: [
                ...tag.folder_ids.filter((id) => id !== body.source_folder_id),
                ...(body.target_folder_id &&
                !tag.folder_ids.includes(body.target_folder_id)
                  ? [body.target_folder_id]
                  : []),
              ],
            }
          : tag,
      );
      return route.fulfill({ status: 204 });
    }
    if (path === "/tag-folders" && request.method() === "POST") {
      const body = request.postDataJSON();
      const created = {
        id: "55555555-5555-4555-8555-555555555555",
        name: body.name,
        parent_id: body.parent_id,
        version: 1,
        tag_count: 0,
        material_count: 0,
        created_at: now,
        updated_at: now,
      };
      folders = [...folders, created];
      return route.fulfill({ status: 201, json: created });
    }
    if (path.startsWith("/tag-folders/") && request.method() === "PUT") {
      const id = path.split("/")[2];
      const body = request.postDataJSON();
      folderUpdates.push({ id, ...body });
      folders = folders.map((folder) =>
        folder.id === id
          ? {
              ...folder,
              name: body.name,
              parent_id: body.parent_id,
              version: folder.version + 1,
            }
          : folder,
      );
      return route.fulfill({
        json: folders.find((folder) => folder.id === id),
      });
    }
    if (path.startsWith("/tag-folders/") && request.method() === "DELETE") {
      const id = path.split("/")[2];
      deleted.push(id);
      folders = folders.filter((folder) => folder.id !== id);
      return route.fulfill({ status: 204 });
    }
    if (path === "/tag-folders") return route.fulfill({ json: folders });
    if (path === "/tags") return route.fulfill({ json: tags });
    if (path === "/tags/unfiled/summary")
      return route.fulfill({ json: { tag_count: 0, material_count: 0 } });
    if (path === "/materials")
      return route.fulfill({ json: { items: [], total: 0 } });
    if (path === "/analysis-targets") return route.fulfill({ json: [] });
    return route.fulfill({
      status: 500,
      json: { detail: `Unexpected ${path}` },
    });
  });

  await page.goto("/results");
  await page.getByRole("button", { name: "5대 교육정책 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "정책 공통", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "RAS 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "RAS 태그", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "세부 정책 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "세부 태그", exact: true }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "RAS", exact: true })
    .click({ button: "right" });
  await page.screenshot({
    path: "../.tmp/frontend/folder-context-menu.png",
    fullPage: true,
  });
  await expect(page.getByRole("button", { name: "폴더 이동" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "RAS", exact: true }).dragTo(
    page.locator(".tree-folder").filter({
      has: page.getByRole("button", { name: "현안", exact: true }),
    }),
  );
  await expect.poll(() => folderUpdates.length).toBe(1);
  expect(folderUpdates[0]).toMatchObject({ id: ids.ras, parent_id: ids.other });

  if (await page.getByRole("button", { name: "현안 펼치기" }).isVisible())
    await page.getByRole("button", { name: "현안 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "RAS", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "세부 태그 끌어서 이동" }).dragTo(
    page.locator(".tree-folder").filter({
      has: page.getByRole("button", { name: "현안", exact: true }),
    }),
  );
  await expect.poll(() => tagMoves.length).toBe(1);
  expect(tagMoves[0]).toEqual({
    tag_id: "leaf-tag",
    source_folder_id: ids.detail,
    target_folder_id: ids.other,
  });
  await expect(
    page.getByRole("button", { name: "세부 태그", exact: true }),
  ).toBeVisible();

  const before = folderUpdates.length;
  await page.getByRole("button", { name: "현안", exact: true }).dragTo(
    page.locator(".tree-folder").filter({
      has: page.getByRole("button", { name: "세부 정책", exact: true }),
    }),
  );
  expect(folderUpdates).toHaveLength(before);

  const movingFolder = page.getByRole("button", { name: "RAS", exact: true });
  await movingFolder.hover();
  const sourceBounds = await movingFolder.boundingBox();
  if (!sourceBounds) throw new Error("이동할 폴더가 화면에 없음");
  await page.mouse.down();
  await page.mouse.move(sourceBounds.x + 12, sourceBounds.y + 12, {
    steps: 5,
  });
  const rootDrop = page.getByRole("button", {
    name: "최상위로 이동",
    exact: true,
  });
  await expect(rootDrop).toBeVisible();
  await rootDrop.hover();
  await rootDrop.hover();
  await page.mouse.up();
  await expect.poll(() => folderUpdates.length).toBe(before + 1);
  expect(folderUpdates.at(-1)).toMatchObject({ id: ids.ras, parent_id: null });

  await page.getByRole("button", { name: "세부 정책 메뉴" }).click();
  await page.getByRole("button", { name: "이름 변경" }).click();
  await page.getByLabel("폴더 이름").fill("세부 정책 수정");
  await page.getByRole("button", { name: "저장" }).click();
  await expect(
    page.getByRole("button", { name: "세부 정책 수정", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "세부 정책 수정", exact: true })
    .click({ button: "right" });
  await page.getByRole("button", { name: "폴더 삭제" }).click();
  await page.getByRole("button", { name: "삭제", exact: true }).click();
  await expect.poll(() => deleted).toContain(ids.detail);
  await expect(
    page.getByRole("button", { name: "세부 정책 수정", exact: true }),
  ).toHaveCount(0);

  const tree = page.locator(".folder-tree");
  const bounds = await tree.boundingBox();
  await tree.click({
    button: "right",
    position: { x: 12, y: (bounds?.height ?? 0) - 8 },
  });
  await page.getByRole("button", { name: "새 폴더" }).click();
  await page.getByLabel("폴더 이름").fill("새 최상위 폴더");
  await page.getByRole("button", { name: "저장" }).click();
  await expect(
    page.getByRole("button", { name: "새 최상위 폴더", exact: true }),
  ).toBeVisible();
});
