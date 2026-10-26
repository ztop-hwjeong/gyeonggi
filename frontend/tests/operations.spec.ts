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
  options: {
    failPreview?: boolean;
    unavailable?: boolean;
    partial?: boolean;
  } = {},
) {
  const writes: {
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }[] = [];
  let previewFailed = false;
  let currentRule = structuredClone(rule);
  let currentRun = options.partial
    ? {
        ...structuredClone(run),
        status: "partial",
        summary: {
          total_count: 20,
          retrieved_count: 12,
          days: [
            {
              date: "2026-06-01",
              total_count: 10,
              retrieved_count: 10,
              complete: true,
            },
            {
              date: "2026-06-02",
              total_count: 10,
              retrieved_count: 2,
              complete: false,
            },
          ],
        },
      }
    : structuredClone(run);
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
          definition: { ...body, version: undefined },
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
      if (path.endsWith("/review")) {
        currentRun = { ...currentRun, reviewed_at: body.reviewed ? now : null };
        return route.fulfill({ json: currentRun });
      }
    }
    if (path === "/overview")
      return route.fulfill({
        json: {
          total_items: 0,
          active_rules: 0,
          total_rules: 1,
          partial_requests: options.partial ? 1 : 0,
          queued_requests: 0,
          failed_requests: 0,
          source_counts: {},
          daily_counts: [{ day: "2026-10-23", count: 0 }],
        },
      });
    if (path === "/keyword-rules")
      return route.fulfill({ json: { items: [currentRule], total: 1 } });
    if (path === `/keyword-rules/${ruleId}/versions`)
      return route.fulfill({
        json: [
          {
            version: currentRule.version,
            definition: currentRule.definition,
            created_at: now,
          },
        ],
      });
    if (path === `/keyword-rules/${ruleId}`)
      return route.fulfill({ json: currentRule });
    if (path === "/collection-runs")
      return route.fulfill({
        json: {
          items: options.partial ? [currentRun] : [],
          total: options.partial ? 1 : 0,
        },
      });
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
    if (path === "/articles" || path === "/materials")
      return route.fulfill({ json: { items: [], total: 0 } });
    if (path === "/analysis-targets") return route.fulfill({ json: [] });
    if (path.endsWith("/targets")) return route.fulfill({ json: [] });
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
  await page.getByLabel("조건 이름").fill("경기 교육");
  await page
    .getByLabel("검색 키워드", { exact: true })
    .fill("경기교육\n경기 교육");
  await page.getByRole("button", { name: "검색 조건 저장" }).click();
  await expect(page).toHaveURL(new RegExp(`/keywords/${ruleId}`));
  expect(writes[0].body).toMatchObject({
    terms: ["경기교육", "경기 교육"],
    enabled: false,
  });
  await page.getByLabel("조건 이름").fill("경기 교육 수정");
  await page.getByRole("button", { name: "검색 조건 저장" }).click();
  await expect(page).toHaveURL(new RegExp(`/keywords/${ruleId}`));
  await expect(page.getByRole("status")).toContainText(
    "검색 조건을 저장했어요",
  );
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
  await page.getByRole("button", { name: "수집 중단", exact: true }).click();
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

test("일부 수집에서 미완료 날짜와 채널을 유지해 보충 요청을 준비한다", async ({
  page,
}) => {
  const writes = await mockApi(page, { partial: true });
  await page.goto(`/runs/${requestId}`);
  await page.getByRole("link", { name: "이 날짜 다시 수집" }).click();
  await expect(page.getByLabel("시작일", { exact: true })).toHaveValue(
    "2026-06-02",
  );
  await expect(page.getByLabel("종료일", { exact: true })).toHaveValue(
    "2026-06-02",
  );
  await expect(page.getByLabel("수집 채널", { exact: true })).toHaveValue(
    "bigkinds",
  );
  expect(writes).toHaveLength(0);
});

test("수집 이력 필터와 페이지를 URL에서 복원하고 채널 변경 시 첫 페이지로 돌아간다", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto(
    "/runs?status=attention&source=bigkinds&mode=backfill&offset=20",
  );
  await expect(page.getByLabel("진행 상태")).toHaveValue("attention");
  const request = page.waitForRequest(
    (request) =>
      request.url().includes("/api/collection-runs?") &&
      request.url().includes("source=naver_blog"),
  );
  await page
    .getByLabel("수집 채널", { exact: true })
    .selectOption("naver_blog");
  expect(new URL((await request).url()).searchParams.get("offset")).toBe("0");
  await expect(page).toHaveURL(/source=naver_blog/);
  await page.goBack();
  await expect(page.getByLabel("수집 채널", { exact: true })).toHaveValue(
    "bigkinds",
  );
});

test("미리보기 뒤 키워드를 바꾸면 이전 조건의 결과임을 알린다", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/keywords/new");
  await page.getByLabel("검색 키워드", { exact: true }).fill("교권보호");
  await page.getByRole("button", { name: "미리보기 실행" }).click();
  await expect(page.getByText("교권 보호 정책 안내")).toBeVisible();
  await page.getByLabel("검색 키워드", { exact: true }).fill("경기교육");
  await expect(page.getByText(/아래는 이전 조건의 결과/)).toBeVisible();
});

test("기사 수집 자료의 검색 조건을 복원한다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/results?kind=news&q=교육&inclusion=excluded&offset=20");
  await expect(page.getByLabel("분석 포함 상태")).toHaveValue("excluded");
  await expect(page.getByLabel("자료 검색")).toHaveValue("교육");
  await page.getByRole("link", { name: "조건 초기화" }).click();
  await expect(page.getByRole("tab", { name: "전체" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByLabel("자료 검색")).toHaveValue("");
});

test("수집 현황에서 확인이 필요한 요청으로 이동한다", async ({ page }) => {
  await mockApi(page, { partial: true });
  await page.goto("/");
  await expect(page.getByText("자동 수집이 모두 꺼져 있어요")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "오류 또는 일부만 수집된 요청 1건" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "확인하고 대응" }).click();
  await expect(page.getByLabel("진행 상태")).toHaveValue("attention");
});

test("검토한 일부 수집을 확인 완료로 표시하고 되돌린다", async ({ page }) => {
  const writes = await mockApi(page, { partial: true });
  await page.goto(`/runs/${requestId}`);
  await page
    .getByRole("button", { name: "확인 완료로 표시", exact: true })
    .click();
  await expect(page.getByText("확인 완료로 표시한 요청이에요")).toBeVisible();
  await expect(page.getByText("일부 수집", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "확인 표시 되돌리기" }).click();
  await expect(
    page.getByRole("button", { name: "확인 완료로 표시", exact: true }),
  ).toBeVisible();
  expect(writes.map((write) => write.body.reviewed)).toEqual([true, false]);
});

test("자료 본문을 읽고 검색하던 위치로 돌아간다", async ({ page }) => {
  await mockApi(page);
  const article = {
    id: "0c0a49b8-0ff5-455b-a17a-5609efafc9cb",
    title: "교육 정책 안내",
    summary: "검색 요약 내용",
    publisher: "교육 소식",
    published_at: now,
    sources: [
      {
        source: "naver_news",
        source_id: "saved-item",
        url: "https://example.com/article",
        original_url: null,
      },
    ],
    inclusion: "include",
    inclusion_reason: null,
    has_body: true,
    body: "확보한 본문 첫 문단\n다음 문단",
    body_collected_at: now,
    content_hash: "hash",
    targets: [],
  };
  const material = {
    ...article,
    kind: "news",
    cafe_name: null,
    cafe_url: null,
    blog_name: null,
    blog_url: null,
    content_preview: "확보한 본문 첫 문단",
  };
  await page.route("**/api/materials?**", (route) =>
    route.fulfill({ json: { items: [material], total: 21 } }),
  );
  await page.route(`**/api/materials/${article.id}`, (route) =>
    route.fulfill({ json: material }),
  );
  await page.goto("/results?q=교육&offset=20");
  await page.getByRole("link", { name: "교육 정책 안내", exact: true }).click();
  await expect(page.getByRole("heading", { name: "본문" })).toBeVisible();
  await expect(page.locator(".article-body")).toContainText(
    "확보한 본문 첫 문단",
  );
  await page.getByRole("link", { name: "수집 자료로 돌아가기" }).click();
  await expect(page).toHaveURL(/offset=20/);
  await expect(page.getByLabel("자료 검색")).toHaveValue("교육");
});

test("기사의 분석 대상 판단을 저장한 뒤 바로 표시한다", async ({ page }) => {
  const articleId = "0c0a49b8-0ff5-455b-a17a-5609efafc9cb";
  let decision = "exclude";
  const article = {
    id: articleId,
    title: "교육 정책 안내",
    summary: "검색 요약 내용",
    publisher: "교육 소식",
    published_at: now,
    sources: [],
    inclusion: "include",
    inclusion_reason: null,
    content_preview: "검색 요약 내용",
    has_body: true,
    body: "본문",
    content_hash: "hash",
    body_collected_at: now,
  };
  const material = {
    ...article,
    kind: "news",
    cafe_name: null,
    cafe_url: null,
    blog_name: null,
    blog_url: null,
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api", "");
    if (path === `/materials/${articleId}`)
      return route.fulfill({ json: material });
    if (path === "/analysis-targets")
      return route.fulfill({
        json: [
          {
            id: "target",
            kind: "policy",
            name: "교권 보호",
            description: "",
            version: 1,
            archived_at: null,
            created_at: now,
          },
        ],
      });
    if (path === `/articles/${articleId}/targets` && request.method() === "GET")
      return route.fulfill({
        json: [
          {
            article_id: articleId,
            target_id: "target",
            decision,
            origin: "manual",
            reason: "판단",
            updated_at: now,
          },
        ],
      });
    if (
      path === `/articles/${articleId}/targets/target` &&
      request.method() === "PUT"
    ) {
      decision = request.postDataJSON().decision;
      return route.fulfill({ json: [] });
    }
    return route.fulfill({
      status: 500,
      json: { detail: `예상하지 않은 API: ${path}` },
    });
  });
  await page.goto(`/results/read?material_id=${articleId}`);
  const targetState = page.locator(".target-list > div > .button-row > span");
  await expect(targetState).toHaveText("제외");
  await page.getByRole("button", { name: "포함", exact: true }).last().click();
  await expect(targetState).toHaveText("포함");
});

test("통합 자료에서 유형별 목록을 구분한다", async ({ page }) => {
  await mockApi(page);
  const items = [
    {
      id: "11111111-1111-4111-8111-111111111111",
      kind: "news",
      title: "기사 제목",
      summary: "기사 요약",
      publisher: "경기일보",
      cafe_name: null,
      cafe_url: null,
      blog_name: null,
      blog_url: null,
      published_at: now,
      sources: [],
      content_preview: "기사 본문 일부",
      has_body: true,
    },
    {
      id: "22222222-2222-4222-8222-222222222222",
      kind: "cafe",
      title: "카페글 제목",
      summary: "카페글 요약",
      publisher: null,
      cafe_name: "교육 카페",
      cafe_url: "https://example.com/cafe",
      blog_name: null,
      blog_url: null,
      published_at: now,
      sources: [],
      content_preview: "",
      has_body: false,
    },
    {
      id: "33333333-3333-4333-8333-333333333333",
      kind: "blog",
      title: "블로그글 제목",
      summary: "블로그글 요약",
      publisher: null,
      cafe_name: null,
      cafe_url: null,
      blog_name: "교육 블로그",
      blog_url: "https://example.com/blog",
      published_at: now,
      sources: [],
      content_preview: "블로그 본문 일부",
      has_body: true,
    },
  ];
  await page.route("**/api/materials?**", (route) => {
    const kind = new URL(route.request().url()).searchParams.get("kind");
    return route.fulfill({
      json: {
        items: kind ? items.filter((item) => item.kind === kind) : items,
        total: kind ? 1 : 3,
      },
    });
  });
  await page.goto("/results");
  await expect(page.getByRole("columnheader", { name: "구분" })).toBeVisible();
  await expect(page.getByText("경기일보")).toBeVisible();
  await page.getByRole("tab", { name: "카페글" }).click();
  await expect(page.getByText("교육 카페")).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: "자료 분류" }),
  ).toBeVisible();
  await expect(page.getByText("기사 제목")).toHaveCount(0);
  await page.getByRole("tab", { name: "블로그글" }).click();
  await expect(page.getByText("교육 블로그")).toBeVisible();
});

test("수집 자료 작업 영역은 데스크톱 가로 폭을 사용한다", async ({ page }) => {
  const item = {
    id: "66666666-6666-4666-8666-666666666666",
    kind: "news",
    title: "경기교육 정책 자료",
    summary: "검색 요약",
    publisher: "경기일보",
    cafe_name: null,
    cafe_url: null,
    blog_name: null,
    blog_url: null,
    published_at: now,
    sources: [],
    content_preview: "본문 일부 내용",
    has_body: true,
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api", "");
    if (path === "/materials")
      return route.fulfill({ json: { items: [item], total: 1 } });
    if (path === "/tag-folders" || path === "/tags")
      return route.fulfill({ json: [] });
    if (path === "/tags/unfiled/summary")
      return route.fulfill({ json: { tag_count: 0, material_count: 0 } });
    if (path === "/analysis-targets") return route.fulfill({ json: [] });
    return route.fulfill({
      status: 500,
      json: { detail: `예상하지 않은 API: ${path}` },
    });
  });
  await page.setViewportSize({ width: 1920, height: 1000 });
  await page.goto("/results");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  const wide = await page
    .locator("main")
    .evaluate((element) => element.clientWidth);
  expect(wide).toBeGreaterThanOrEqual(1680);
  await page.screenshot({
    path: "../.tmp/frontend/results-wide.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const standard = await page
    .locator("main")
    .evaluate((element) => element.clientWidth);
  expect(standard).toBeGreaterThanOrEqual(1200);
});

test("미분류 태그를 폴더에 편입하고 기사 수를 갱신한다", async ({ page }) => {
  const tagId = "topic-1";
  const rootFolderId = "77777777-7777-4777-8777-777777777777";
  const folderId = "44444444-4444-4444-8444-444444444444";
  const articleId = "55555555-5555-4555-8555-555555555555";
  let attached = false;
  const article = {
    id: articleId,
    title: "태그가 붙은 기사",
    summary: "요약",
    publisher: "경기일보",
    published_at: now,
    sources: [],
    inclusion: "include",
    inclusion_reason: null,
    content_preview: "본문 일부",
    has_body: true,
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api", "");
    if (path === "/materials")
      return route.fulfill({ json: { items: [], total: 0 } });
    if (path === "/analysis-targets") return route.fulfill({ json: [] });
    if (path === "/tag-folders")
      return route.fulfill({
        json: [
          {
            id: rootFolderId,
            parent_id: null,
            name: "정책 자료",
            version: 1,
            tag_count: attached ? 1 : 0,
            material_count: attached ? 1 : 0,
            created_at: now,
            updated_at: now,
          },
          {
            id: folderId,
            parent_id: rootFolderId,
            name: "검토",
            version: 1,
            tag_count: attached ? 1 : 0,
            material_count: attached ? 1 : 0,
            created_at: now,
            updated_at: now,
          },
        ],
      });
    if (path === "/tags/unfiled/summary")
      return route.fulfill({
        json: { tag_count: attached ? 0 : 1, material_count: attached ? 0 : 1 },
      });
    if (path === "/tags")
      return route.fulfill({
        json: [
          {
            id: tagId,
            name: "교권",
            description: "",
            synonyms: [],
            version: 1,
            material_count: 1,
            folder_ids: attached ? [folderId] : [],
            created_at: now,
            updated_at: now,
          },
        ],
      });
    if (path === "/articles")
      return route.fulfill({ json: { items: [article], total: 1 } });
    if (
      path === `/tag-folders/${folderId}/tags` &&
      request.method() === "POST"
    ) {
      attached = true;
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({
      status: 500,
      json: { detail: `예상하지 않은 API: ${path}` },
    });
  });
  await page.goto("/results?kind=news");
  await expect(
    page.getByRole("button", { name: "미분류 태그 펼치기" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "미분류 태그 펼치기" }).click();
  await page.screenshot({
    path: "../.tmp/frontend/results-tree.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "교권", exact: true }).click();
  await expect(page.getByText("태그가 붙은 기사")).toBeVisible();
  await page.getByRole("checkbox", { name: "교권" }).check();
  await page.getByRole("button", { name: "정책 자료 펼치기" }).click();
  await page.getByRole("button", { name: "검토", exact: true }).click();
  await page.getByRole("button", { name: "선택 태그 편입" }).click();
  await expect(
    page.getByRole("button", { name: "검토", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".tree-folder")
      .filter({ hasText: "검토" })
      .getByText("자료 1"),
  ).toBeVisible();
  await expect(page.getByText("전체 1건")).toBeVisible();
  await expect(
    page.locator(".tree-folder").first().locator("small"),
  ).toHaveText("자료 0");
  await page.getByRole("button", { name: "검토 펼치기" }).click();
  await expect(
    page.getByRole("button", { name: "교권", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../.tmp/frontend/results-tree.png",
    fullPage: true,
  });
});

test("사이드바를 접어도 메뉴 이동과 선택 상태를 유지한다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/results");
  const menuIcons = page.locator(".sidebar nav a svg");
  const expandedPositions = await menuIcons.evaluateAll((icons) =>
    icons.map((icon) => {
      const { x, y } = icon.getBoundingClientRect();
      return { x, y };
    }),
  );
  await page.getByRole("button", { name: "메뉴 접기" }).click();
  await expect(page.locator(".sidebar")).toHaveAttribute(
    "data-collapsed",
    "true",
  );
  await expect
    .poll(async () =>
      page
        .locator(".sidebar")
        .evaluate((element) =>
          Math.round(element.getBoundingClientRect().width),
        ),
    )
    .toBe(64);
  expect(
    await menuIcons.evaluateAll((icons) =>
      icons.map((icon) => {
        const { x, y } = icon.getBoundingClientRect();
        return { x, y };
      }),
    ),
  ).toEqual(expandedPositions);
  await page.screenshot({
    path: "../.tmp/frontend/results-collapsed-sidebar.png",
    fullPage: true,
  });
  await expect(
    page.getByRole("link", { name: "수집 자료", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await page.reload();
  await expect(page.locator(".sidebar")).toHaveAttribute(
    "data-collapsed",
    "true",
  );
  await page.getByRole("link", { name: "키워드 관리", exact: true }).click();
  await expect(page).toHaveURL(/keywords/);
  await page.getByRole("button", { name: "메뉴 펼치기" }).click();
  await expect(page.locator(".sidebar")).toHaveAttribute(
    "data-collapsed",
    "false",
  );
  await expect
    .poll(async () =>
      page
        .locator(".sidebar")
        .evaluate((element) =>
          Math.round(element.getBoundingClientRect().width),
        ),
    )
    .toBe(224);
});

test("저장 전 다른 메뉴로 이동하면 변경 내용 유실을 확인한다", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/keywords/new");
  await page.getByLabel("조건 이름").fill("저장 전 조건");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "수집 자료", exact: true })
    .click();
  await expect(page).toHaveURL(/keywords\/new$/);
  await expect(page.getByLabel("조건 이름")).toHaveValue("저장 전 조건");
});
