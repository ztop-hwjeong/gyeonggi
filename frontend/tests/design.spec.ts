import { expect, test } from "@playwright/test";

test("자료 제목 하나로 열고 검색하던 목록과 포커스를 복원한다", async ({
  page,
}) => {
  const requests: string[] = [];
  await page.route("**/api/**", (route) => {
    requests.push(route.request().url());
    return route.abort();
  });
  await page.goto("/design");
  await expect(page.getByRole("navigation", { name: "주 메뉴" })).toHaveCount(
    0,
  );
  await expect(page.getByText(/원문|본문 확보|목록 확보/)).toHaveCount(0);
  await page.getByLabel("자료 검색").fill("교권");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  const title = page.getByRole("button", {
    name: /학교 현장의 교권 보호 지원 방안/,
  });
  await expect(title).toBeVisible();
  await title.click();
  await expect(
    page.getByRole("heading", { name: "학교 현장의 교권 보호 지원 방안" }),
  ).toBeFocused();
  await page.getByRole("button", { name: "목록으로" }).click();
  await expect(page.getByLabel("자료 검색")).toHaveValue("교권");
  await expect(title).toBeFocused();
  expect(requests).toEqual([]);
});

test("탭을 키보드로 전환하고 필수 입력 오류에서 내용을 유지한다", async ({
  page,
}) => {
  await page.goto("/design");
  await page.getByRole("tab", { name: "자료 읽기" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "키워드 입력" })).toBeFocused();
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByLabel("키워드 이름")).toBeFocused();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "키워드 이름을 적어 주세요",
  );
  await page.getByLabel("키워드 이름").fill("교권 보호");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByLabel("검색어", { exact: true })).toBeFocused();
  await expect(page.getByLabel("키워드 이름")).toHaveValue("교권 보호");
  await page.getByLabel("검색어", { exact: true }).fill("교권보호, 교권 보호");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "예시 화면에만 적용돼요",
  );
});

test("모바일에서 채널로 검색하고 오류를 재시도한다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/design");
  await expect(page.getByLabel("찾을 곳")).toBeVisible();
  await page.getByLabel("찾을 곳").selectOption("blog");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /교육 활동 중 어려움/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /학교 현장의 교권/ }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("tab", { name: "알림", exact: true }).click();
  await page.getByLabel("확인할 상태").selectOption("error");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "자료를 불러오지 못했어요",
  );
  await page.getByRole("button", { name: "다시 시도" }).click();
  await expect(
    page.getByRole("heading", { name: "아직 모은 자료가 없어요" }),
  ).toBeVisible();
});
