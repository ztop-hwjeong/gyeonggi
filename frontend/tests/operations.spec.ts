import { expect, type Page, test } from "@playwright/test";
import type { Schema } from "../src/shared/api/client";

const ruleId = "11111111-1111-4111-8111-111111111111";
const requestId = "22222222-2222-4222-8222-222222222222";
const now = "2026-10-23T09:00:00Z";
const rule: Schema["RuleInfo"] = {
  id: ruleId,
  version: 1,
  created_at: now,
  updated_at: now,
  definition: {
    name: "교권 보호",
    description: "교육 정책",
    terms: ["교권보호"],
    sources: ["bigkinds", "naver_blog"],
    enabled: false,
    interval_minutes: 15,
  },
};
const run: Schema["RequestInfo"] = {
  id: requestId,
  rule_id: ruleId,
  rule_version: 1,
  definition: rule.definition,
  source: "bigkinds",
  mode: "backfill",
  start_date: "2026-06-01",
  end_date: "2026-10-23",
  status: "queued",
  flow_run_id: null,
  summary: {},
  error: null,
  created_at: now,
  updated_at: now,
};

async function mockApi(
  page: Page,
  options: { failPreview?: boolean; unavailable?: boolean } = {},
) {
  const writes: {
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }[] = [];
  let previewFailed = false;
  let currentRule = structuredClone(rule);
  let currentRun = structuredClone(run);
  await page.route("**/api/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname.replace("/api", "");
    if (options.unavailable)
      return route.fulfill({
        status: 503,
        json: { detail: "수집 저장소 연결 실패" },
      });
    if (["POST", "PUT"].includes(request.method())) {
      const body = request.postDataJSON();
      writes.push({ path, body, key: request.headers()["idempotency-key"] });
      if (path === "/keyword-rules" || path === `/keyword-rules/${ruleId}`) {
        currentRule = {
          ...currentRule,
          definition: body,
          version: request.method() === "PUT" ? 2 : 1,
        };
        return route.fulfill({
          json: currentRule,
          status: request.method() === "POST" ? 201 : 200,
        });
      }
      if (path === "/collection-previews") {
        if (options.failPreview && !previewFailed) {
          previewFailed = true;
          return route.abort("failed");
        }
        currentRun = {
          ...run,
          mode: "preview",
          status: "completed",
          summary: { total_count: 12, retrieved_count: 1 },
        };
        return route.fulfill({ json: currentRun, status: 202 });
      }
      if (path === "/collection-runs")
        return route.fulfill({ json: currentRun, status: 202 });
      if (path.endsWith("/cancel")) {
        currentRun = { ...currentRun, status: "cancelled" };
        return route.fulfill({ json: currentRun, status: 202 });
      }
    }
    if (path === "/overview")
      return route.fulfill({
        json: {
          total_items: 0,
          active_rules: 0,
          queued_requests: 0,
          failed_requests: 0,
          source_counts: {},
          daily_counts: [{ day: "2026-10-23", count: 0 }],
        },
      });
    if (path === "/keyword-rules")
      return route.fulfill({ json: { items: [currentRule], total: 1 } });
    if (path === `/keyword-rules/${ruleId}`)
      return route.fulfill({ json: currentRule });
    if (path === "/collection-runs")
      return route.fulfill({ json: { items: [], total: 0 } });
    if (path === `/collection-runs/${requestId}`)
      return route.fulfill({ json: currentRun });
    if (path.endsWith("/items"))
      return route.fulfill({
        json: {
          items:
            currentRun.mode === "preview"
              ? [
                  {
                    source_id: "article",
                    title: "교권 보호 정책 안내",
                    summary: "학교 지원 정책을 발표했다.",
                  },
                ]
              : [],
          total: currentRun.mode === "preview" ? 1 : 0,
        },
      });
    if (path === "/articles")
      return route.fulfill({ json: { items: [], total: 0 } });
    if (path === "/monitoring/workers")
      return route.fulfill({ json: { observed_at: now, pools: [] } });
    return route.fulfill({
      status: 500,
      json: { detail: `예상하지 않은 API: ${path}` },
    });
  });
  return writes;
}

test("키워드 등록과 수정에 입력 조건과 조회 버전을 전달한다", async ({
  page,
}) => {
  const writes = await mockApi(page);
  await page.goto("/keywords/new");
  await page.getByLabel("규칙 이름").fill("경기 교육");
  await page
    .getByLabel("검색 키워드", { exact: true })
    .fill("경기교육\n경기 교육");
  await page.getByRole("button", { name: "규칙 저장" }).click();
  await expect(page).toHaveURL(/\/keywords$/);
  expect(writes[0].body).toMatchObject({
    terms: ["경기교육", "경기 교육"],
    enabled: false,
  });
  await page.getByRole("link", { name: "경기 교육", exact: true }).click();
  await page.getByLabel("규칙 이름").fill("경기 교육 수정");
  await page.getByRole("button", { name: "규칙 저장" }).click();
  await expect(page).toHaveURL(/\/keywords$/);
  expect(writes[1].body.version).toBe(1);
});

test("미리보기 통신 실패 재시도에 동일 요청 키를 재사용한다", async ({
  page,
}) => {
  const writes = await mockApi(page, { failPreview: true });
  await page.goto("/keywords/new");
  await page.getByLabel("검색 키워드", { exact: true }).fill("교권보호");
  await page.getByRole("button", { name: "미리보기 실행" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await page.getByRole("button", { name: "미리보기 실행" }).click();
  await expect(page.getByText("교권 보호 정책 안내")).toBeVisible();
  expect(writes).toHaveLength(2);
  expect(writes[0].key).toBeTruthy();
  expect(writes[0].key).toBe(writes[1].key);
});

test("과거 수집 요청과 대기 요청 취소를 연결한다", async ({ page }) => {
  const writes = await mockApi(page);
  await page.goto(`/runs/new?rule=${ruleId}`);
  await page.getByLabel("시작일", { exact: true }).fill("2026-06-01");
  await page.getByLabel("종료일", { exact: true }).fill("2026-10-23");
  await page.getByRole("button", { name: "수집 요청", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${requestId}$`));
  expect(writes[0].body).toMatchObject({
    mode: "backfill",
    version: 1,
    start_date: "2026-06-01",
    end_date: "2026-10-23",
  });
  await page.getByRole("button", { name: "실행 취소" }).click();
  await expect(page.getByText("취소됨", { exact: true })).toBeVisible();
});

test("네이버를 선택하면 기간 입력 대신 증분 수집을 안내한다", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto(`/runs/new?rule=${ruleId}`);
  await page
    .getByLabel("수집 채널", { exact: true })
    .selectOption("naver_blog");
  await expect(page.getByLabel("시작일", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText(/기간을 지정한 과거 수집은 지원하지/),
  ).toBeVisible();
});

test("조회 오류를 빈 결과로 표시하지 않는다", async ({ page }) => {
  await mockApi(page, { unavailable: true });
  await page.goto("/results");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "수집 저장소 연결 실패",
  );
  await expect(page.getByText("아직 수집된 자료가 없어요")).toHaveCount(0);
});

test("모바일 메뉴와 작업 화면이 화면 너비를 넘지 않는다", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "메뉴 열기" }).click();
  await expect(page.getByRole("navigation", { name: "주 메뉴" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("navigation", { name: "주 메뉴" }),
  ).not.toBeVisible();
  await page.goto("/keywords/new");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
