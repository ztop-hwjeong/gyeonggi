import { expect, type Page, test } from "@playwright/test";

const now = "2026-10-30T09:00:00Z";
const targetId = "33333333-3333-4333-8333-333333333333";
const reportId = "44444444-4444-4444-8444-444444444444";
const articleId = "55555555-5555-4555-8555-555555555555";
const report = {
  id: reportId,
  target_id: targetId,
  target_kind: "current_issue",
  title: "현안 분석 보고서",
  description: "",
  keyword_terms: ["황현필"],
  keywords_automatic: true,
  is_default: true,
  start_at: null,
  end_at: null,
  version: 1,
  created_at: now,
  updated_at: now,
};

async function mockWorkspace(page: Page) {
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  let currentReport = structuredClone(report);
  let reports = [currentReport];
  let reportDecision: "include" | "exclude" | null = null;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api", "");
    if (path === "/analysis-targets")
      return route.fulfill({
        json: [
          {
            id: targetId,
            kind: "current_issue",
            name: "현안 분석",
            description: "현안 기사 분석",
            version: 1,
            collection_enabled: true,
            archived_at: null,
            created_at: now,
            updated_at: now,
          },
        ],
      });
    if (path === "/analysis-reports" && request.method() === "GET")
      return route.fulfill({ json: reports });
    if (path === "/analysis-reports" && request.method() === "POST") {
      const body = request.postDataJSON();
      writes.push({ path, body });
      const created = {
        ...structuredClone(report),
        id: "66666666-6666-4666-8666-666666666666",
        title: "추가 보고서",
        target_id: body.target_id,
        version: 1,
      };
      reports = [...reports, created];
      return route.fulfill({ status: 201, json: created });
    }
    if (path === `/analysis-reports/${reportId}` && request.method() === "GET")
      return route.fulfill({ json: currentReport });
    if (
      path === `/analysis-reports/${reportId}` &&
      request.method() === "DELETE"
    ) {
      writes.push({ path, body: { version: url.searchParams.get("version") } });
      reports = reports.filter((item) => item.id !== reportId);
      return route.fulfill({ status: 204 });
    }
    if (
      path === `/analysis-reports/${reportId}` &&
      request.method() === "PUT"
    ) {
      const body = request.postDataJSON();
      writes.push({ path, body });
      currentReport = {
        ...currentReport,
        ...body,
        keyword_terms:
          body.keywords_automatic === true
            ? ["황현필"]
            : (body.keyword_terms ?? currentReport.keyword_terms),
        keywords_automatic:
          body.keywords_automatic ?? currentReport.keywords_automatic,
        version: currentReport.version + 1,
      };
      reports = [currentReport, ...reports.slice(1)];
      return route.fulfill({ json: currentReport });
    }
    if (path === `/analysis-reports/${reportId}/articles`)
      return route.fulfill({
        json: {
          items:
            url.searchParams.get("keyword_match") === "unmatched"
              ? []
              : [
                  {
                    id: articleId,
                    title: "현안 관련 기사",
                    summary: "요약",
                    content_preview: "본문",
                    publisher: "경기일보",
                    original_published_at: now,
                    is_keyword_match: true,
                    matched_keywords: ["황현필"],
                    report_decision: reportDecision,
                    report_decision_reason: null,
                    ai_status: "outdated",
                    ai_relevance: "related",
                    ai_reason: null,
                    ai_evidence: [],
                  },
                ],
          total: 12,
          filtered_total:
            url.searchParams.get("keyword_match") === "unmatched" ? 0 : 1,
          matched: 7,
          unmatched: 5,
          included: 12,
          excluded: 0,
        },
      });
    if (path === `/analysis-reports/${reportId}/articles/${articleId}`)
      return route.fulfill({
        json: {
          id: articleId,
          title: "현안 관련 기사",
          summary: "수집 요약",
          content_preview: "최신 본문 일부",
          body: "본문",
          content_hash: null,
          publisher: "경기일보",
          original_published_at: now,
          is_keyword_match: true,
          matched_keywords: ["황현필"],
          report_decision: null,
          report_decision_reason: null,
          ai_status: "completed",
          ai_relevance: "related",
          ai_reason: "교육청 행사와 직접 관련",
          ai_evidence: ["경기도교육청 특강 언급"],
        },
      });
    if (
      path === `/analysis-reports/${reportId}/articles/${articleId}/decision`
    ) {
      const body = request.postDataJSON();
      writes.push({ path, body });
      reportDecision = body.decision === "release" ? null : body.decision;
      return route.fulfill({ status: 204 });
    }
    if (path === `/analysis-reports/${reportId}/relevance/preview`) {
      const body = request.postDataJSON();
      writes.push({ path, body });
      return route.fulfill({
        json: {
          eligible: body.scope === "selected" ? body.article_ids.length : 8,
          skipped_no_body: 2,
          skipped_excluded: 1,
          skipped_current: 3,
          pending: 1,
          estimated_input_tokens: 1200,
          estimated_output_tokens: 240,
          estimated_cost_usd: 0.00024,
          model: "gpt-6-luna",
          fingerprint: "a".repeat(64),
        },
      });
    }
    if (path === `/analysis-reports/${reportId}/relevance/runs`) {
      writes.push({ path, body: request.postDataJSON() });
      return route.fulfill({
        json: {
          batch_id: "77777777-7777-4777-8777-777777777777",
          queued: 1,
          reused: 0,
        },
      });
    }
    return route.fulfill({
      status: 500,
      json: { detail: `예상하지 않은 API: ${path}` },
    });
  });
  return writes;
}

test("보고서 기사 상세 패널을 열고 닫아 목록 상태를 유지한다", async ({
  page,
}) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api", "");
    if (path === "/analysis-targets")
      return route.fulfill({
        json: [
          {
            id: targetId,
            kind: "current_issue",
            name: "현안 분석",
            description: "현안 기사 분석",
            version: 1,
            collection_enabled: true,
            archived_at: null,
            created_at: now,
            updated_at: now,
          },
        ],
      });
    if (path === "/analysis-reports") return route.fulfill({ json: [report] });
    if (path === `/analysis-reports/${reportId}`)
      return route.fulfill({ json: report });
    if (path === `/analysis-reports/${reportId}/articles`)
      return route.fulfill({
        json: {
          items: [
            {
              id: articleId,
              title: "현안 관련 기사",
              summary: "수집 요약",
              content_preview: "최신 본문 일부",
              publisher: "경기일보",
              original_published_at: now,
              is_keyword_match: true,
              matched_keywords: ["황현필"],
              report_decision: null,
            },
          ],
          total: 1,
          filtered_total: 1,
          matched: 1,
          unmatched: 0,
          included: 1,
          excluded: 0,
        },
      });
    if (path === `/analysis-reports/${reportId}/articles/${articleId}`)
      return route.fulfill({
        json: {
          id: articleId,
          title: "현안 관련 기사",
          summary: "수집 요약",
          content_preview: "최신 본문 일부",
          body: "본문",
          content_hash: null,
          publisher: "경기일보",
          original_published_at: now,
          is_keyword_match: true,
          matched_keywords: ["황현필"],
          report_decision: null,
          report_decision_reason: null,
          ai_status: "unjudged",
          ai_relevance: null,
          ai_reason: null,
          ai_evidence: [],
        },
      });
    if (path === `/materials/${articleId}`)
      return route.fulfill({
        json: {
          id: articleId,
          kind: "news",
          title: "현안 관련 기사",
          summary: "수집 요약",
          content_preview: "최신 본문 일부",
          body: "본문",
          body_skip_reason: null,
          publisher: "경기일보",
          original_published_at: now,
          published_at: now,
          published_on: null,
          sources: [],
        },
      });
    if (path === `/articles/${articleId}/targets`)
      return route.fulfill({ json: [] });
    if (path === `/articles/${articleId}/sentiment`)
      return route.fulfill({ json: {} });
    if (path === `/articles/${articleId}/reprints`)
      return route.fulfill({ json: [] });
    if (path === `/articles/${articleId}/discovery-paths`)
      return route.fulfill({ json: [] });
    return route.fulfill({
      status: 500,
      json: { detail: `예상하지 않은 API: ${path}` },
    });
  });

  await page.goto(
    `/analysis-reports?kind=current_issue&report_id=${reportId}&keyword_match=matched&offset=20`,
  );
  await page.getByRole("button", { name: "현안 관련 기사" }).click();
  await expect(page.getByRole("dialog")).toContainText("현안 관련 기사");
  await page.getByRole("button", { name: "닫기" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page).toHaveURL(/keyword_match=matched/);
  await expect(page).toHaveURL(/offset=20/);
});

test("보고서 필터와 로컬 포함 판단 요청을 일치시킨다", async ({ page }) => {
  const writes = await mockWorkspace(page);
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes(`/analysis-reports/${reportId}/articles?`))
      requests.push(request.url());
  });
  await page.goto(`/analysis-reports?kind=current_issue&report_id=${reportId}`);
  await page
    .getByRole("table")
    .getByRole("button", { name: "제외", exact: true })
    .click();
  await page
    .getByRole("table")
    .getByRole("button", { name: "해제", exact: true })
    .click();
  expect(writes.filter((item) => item.path.endsWith("/decision"))).toEqual([
    {
      path: `/analysis-reports/${reportId}/articles/${articleId}/decision`,
      body: { decision: "exclude", reason: "보고서 검토" },
    },
    {
      path: `/analysis-reports/${reportId}/articles/${articleId}/decision`,
      body: { decision: "release", reason: "" },
    },
  ]);
  await page.getByRole("tab", { name: "키워드 불일치" }).click();
  await expect(page.getByText("전체 0건")).toBeVisible();
  await page
    .getByRole("group", { name: "검토 결정" })
    .getByRole("button", { name: "제외" })
    .click();
  await expect.poll(() => requests.at(-1)).toContain("keyword_match=unmatched");
  await expect.poll(() => requests.at(-1)).toContain("inclusion=excluded");
});

test("키워드 편집만 자동 연결을 수동값으로 바꾸고 복원한다", async ({
  page,
}) => {
  const writes = await mockWorkspace(page);
  await page.goto(`/analysis-reports?kind=current_issue&report_id=${reportId}`);
  await page.getByRole("button", { name: "설정", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "보고서 설정" });
  await expect
    .poll(() => settings.evaluate((node) => node.matches(":modal")))
    .toBe(true);
  await page.getByLabel("보고서 제목").fill("기간만 수정");
  await page.getByLabel("발행시각 시작").fill("2026-10-28T15:00");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  expect(writes[0].body).not.toHaveProperty("keywords_automatic");
  await page.getByRole("button", { name: "설정", exact: true }).click();
  await page.getByLabel("검토 키워드").fill("새 키워드");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  expect(writes[1].body).toMatchObject({
    keywords_automatic: false,
    keyword_terms: ["새 키워드"],
  });
  await page.getByRole("button", { name: "설정", exact: true }).click();
  await page.getByRole("button", { name: "자동 채움 복원" }).click();
  expect(writes[2].body).toMatchObject({ keywords_automatic: true });
  await expect(page.getByLabel("검토 키워드")).toHaveValue("황현필");
});

test("새 보고서는 대상 선택을 유지해 생성 뒤 목록에서 연다", async ({
  page,
}) => {
  const writes = await mockWorkspace(page);
  await page.goto(`/analysis-reports?kind=current_issue&target_id=${targetId}`);
  await expect(
    page.getByRole("tab", { name: "현안 분석 보고서" }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "새 보고서" }).click();
  const dialog = page.getByRole("dialog", { name: "새 보고서" });
  await expect
    .poll(() => dialog.evaluate((node) => node.matches(":modal")))
    .toBe(true);
  await dialog.getByRole("button", { name: /현안 분석/ }).click();
  await dialog.getByRole("button", { name: "만들기" }).click();
  expect(writes[0]).toEqual({
    path: "/analysis-reports",
    body: { target_id: targetId },
  });
  await expect(page).toHaveURL(
    /report_id=66666666-6666-4666-8666-666666666666/,
  );
});

test("선택 및 현재 검색 결과 범위를 미리보기 후 fingerprint로 실행한다", async ({
  page,
}) => {
  const writes = await mockWorkspace(page);
  await page.goto(`/analysis-reports?kind=current_issue&report_id=${reportId}`);
  await expect(page.getByRole("table").getByText("이전 기준")).toBeVisible();
  await page.getByLabel("현안 관련 기사 선택").check();
  await page.getByRole("button", { name: "선택한 1건 판정" }).click();
  await expect(page.getByRole("dialog")).toContainText("판정 대상1건");
  await expect(page.getByRole("dialog")).toContainText("본문 없음2건");
  await expect(page.getByRole("dialog")).toContainText("제외됨1건");
  await expect(page.getByRole("dialog")).toContainText("예상 비용$0.0002");
  await expect(page.getByRole("dialog")).toContainText(
    "실제 비용은 사용량과 캐시에 따라",
  );
  expect(writes.filter((item) => item.path.endsWith("/runs"))).toHaveLength(0);
  expect(
    writes.find((item) => item.path.endsWith("/preview"))?.body,
  ).toMatchObject({
    scope: "selected",
    article_ids: [articleId],
    mode: "unjudged",
  });
  await page.getByRole("button", { name: "판정 시작" }).click();
  expect(
    writes.find((item) => item.path.endsWith("/runs"))?.body,
  ).toMatchObject({
    scope: "selected",
    article_ids: [articleId],
    preview_fingerprint: "a".repeat(64),
  });
  await page.getByRole("button", { name: "현재조건 미판정 기사 판정" }).click();
  expect(
    writes.filter((item) => item.path.endsWith("/preview")).at(-1)?.body,
  ).toMatchObject({ scope: "filtered", article_ids: [] });
});

test("상세 패널은 AI 근거를 보여주고 Escape 후 행으로 초점을 돌린다", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto(`/analysis-reports?kind=current_issue&report_id=${reportId}`);
  const trigger = page.getByRole("button", { name: "현안 관련 기사" });
  await trigger.click();
  await expect
    .poll(() =>
      page.getByRole("dialog").evaluate((node) => node.matches(":modal")),
    )
    .toBe(true);
  await expect(page.getByRole("dialog")).toContainText("본문");
  await expect(page.getByRole("dialog")).toContainText("AI 관련성");
  await expect(page.getByRole("dialog")).toContainText(
    "교육청 행사와 직접 관련",
  );
  await expect(page.getByRole("dialog")).toContainText(
    "경기도교육청 특강 언급",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("미검토·AI 관련성 조합과 실패 재시도 모드를 요청한다", async ({
  page,
}) => {
  const writes = await mockWorkspace(page);
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes(`/analysis-reports/${reportId}/articles?`))
      requests.push(request.url());
  });
  await page.goto(`/analysis-reports?kind=current_issue&report_id=${reportId}`);
  const unreviewed = page
    .getByRole("group", { name: "검토 결정" })
    .getByRole("button", { name: "미검토" });
  await unreviewed.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/inclusion=unreviewed/);
  await page
    .getByRole("group", { name: "AI 관련성" })
    .getByRole("button", { name: "실패" })
    .click();
  await expect.poll(() => requests.at(-1)).toContain("inclusion=unreviewed");
  await expect.poll(() => requests.at(-1)).toContain("ai_relevance=failed");
  await page.getByRole("button", { name: "실패 재시도" }).click();
  expect(writes.at(-1)).toMatchObject({
    path: `/analysis-reports/${reportId}/relevance/preview`,
    body: {
      scope: "filtered",
      mode: "failed",
      inclusion: "unreviewed",
      ai_relevance: "failed",
    },
  });
});

test("보고서 삭제는 확인 후 실행하고 취소 시 요청하지 않는다", async ({
  page,
}) => {
  const writes = await mockWorkspace(page);
  await page.goto(`/analysis-reports?kind=current_issue&report_id=${reportId}`);
  await page.getByRole("button", { name: "보고서 삭제", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "보고서를 삭제할까요?" });
  await expect(dialog).toContainText("현안 분석 보고서");
  await expect(dialog).toContainText("기사 원문");
  await dialog.getByRole("button", { name: "취소" }).click();
  expect(writes).toHaveLength(0);
  await page.getByRole("button", { name: "보고서 삭제", exact: true }).click();
  await dialog.getByRole("button", { name: "삭제", exact: true }).click();
  await expect(page).not.toHaveURL(/report_id=/);
  expect(writes).toEqual([
    { path: `/analysis-reports/${reportId}`, body: { version: "1" } },
  ]);
});

test("진행 중 AI 판정으로 삭제가 거절되면 보고서를 유지한다", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.route(
    `**/api/analysis-reports/${reportId}?version=*`,
    async (route) => {
      if (route.request().method() === "DELETE")
        return route.fulfill({
          status: 409,
          json: {
            detail: "진행 중인 AI 판정이 있습니다. 완료 후 삭제해 주세요.",
          },
        });
      return route.fallback();
    },
  );
  await page.goto(`/analysis-reports?kind=current_issue&report_id=${reportId}`);
  await page.getByRole("button", { name: "보고서 삭제", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "삭제", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "진행 중인 AI 판정",
  );
  await page.getByRole("button", { name: "취소" }).click();
  await expect(
    page.getByRole("heading", { name: "현안 분석 보고서" }),
  ).toBeVisible();
});
