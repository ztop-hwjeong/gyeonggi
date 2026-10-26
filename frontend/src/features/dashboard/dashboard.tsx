"use client";

import { ArrowRightIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { RunTable } from "@/features/runs/run-table";
import { type Schema, useApi } from "@/shared/api/client";
import { number, sourceNames } from "@/shared/lib/format";
import { ErrorNotice, Loading, PageHeading } from "@/shared/ui/feedback";
import { OperationsSummary } from "./operations-summary";

export function Dashboard() {
  const overview = useApi<Schema["Overview"]>("/overview");
  const runs = useApi<Schema["RequestPage"]>("/collection-runs?limit=5");
  const data = overview.data;
  const maximum = Math.max(
    1,
    ...(data?.daily_counts.map((day) => day.count) ?? []),
  );
  return (
    <>
      <PageHeading
        title="수집 현황"
        action={
          <Link href="/runs" className="button secondary">
            수집 이력 보기 <ArrowRightIcon size={18} />
          </Link>
        }
      />
      {overview.error && (
        <ErrorNotice error={overview.error} retry={() => overview.refetch()} />
      )}
      {overview.isLoading ? (
        <Loading />
      ) : (
        data && (
          <>
            <OperationsSummary data={data} />{" "}
            <section className="panel summary-strip" aria-label="수집 요약">
              {[
                ["누적 수집 자료", data.total_items, "건"],
                ["자동 수집 조건", data.active_rules, "개"],
                ["대기·진행 중", data.queued_requests, "건"],
                [
                  "24시간 오류·일부 수집",
                  data.failed_requests + data.partial_requests,
                  "건",
                ],
              ].map(([label, value, unit]) => (
                <div className="summary-stat" key={label}>
                  <span>{label}</span>
                  <strong>
                    {number(value as number)}
                    <small>{unit}</small>
                  </strong>
                </div>
              ))}
            </section>
            <div className="dashboard-grid">
              <section className="panel">
                <div className="panel-header">
                  <h2>최근 7일 수집 추이</h2>
                  <span className="hint">신규 저장 기준 · 한국 시각</span>
                </div>
                <div className="panel-body">
                  <figure
                    style={{ margin: 0 }}
                    aria-label="날짜별 신규 저장 자료 수"
                  >
                    <div className="chart">
                      {data.daily_counts.map((day) => (
                        <div className="chart-column" key={day.day}>
                          <b>{number(day.count)}</b>
                          <div className="chart-bar-area">
                            <div
                              className="chart-bar"
                              style={{
                                height: `${(day.count / maximum) * 100}%`,
                              }}
                            />
                          </div>
                          <span>{day.day.slice(5).replace("-", ".")}</span>
                        </div>
                      ))}
                    </div>
                    <figcaption className="sr-only">
                      {data.daily_counts
                        .map((day) => `${day.day} ${day.count}건`)
                        .join(", ")}
                    </figcaption>
                  </figure>
                </div>
              </section>
              <section className="panel">
                <div className="panel-header">
                  <h2>채널별 수집 자료</h2>
                </div>
                <div className="panel-body">
                  <ul className="channel-list">
                    {Object.entries(sourceNames).map(([code, name]) => (
                      <li key={code}>
                        <span className="channel-name">
                          <span
                            className={`channel-dot ${code.startsWith("naver") ? "naver" : ""}`}
                          />
                          {name}
                        </span>
                        <Link
                          href={`/results?source=${code}`}
                          aria-label={`${name} 자료 보기`}
                        >
                          {number(data.source_counts[code] ?? 0)}건{" "}
                          <ArrowRightIcon size={14} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                  <Link
                    href="/results"
                    className="button quiet"
                    style={{ marginTop: 12 }}
                  >
                    수집 결과 보기 <ArrowRightIcon size={16} />
                  </Link>
                </div>
              </section>
            </div>
          </>
        )
      )}
      <section className="panel section-gap">
        <div className="panel-header" style={{ paddingBottom: 22 }}>
          <h2>최근 수집 이력</h2>
          <Link href="/runs" className="button quiet">
            전체 보기 <ArrowRightIcon size={16} />
          </Link>
        </div>
        {runs.error ? (
          <div className="panel-body">
            <ErrorNotice error={runs.error} retry={() => runs.refetch()} />
          </div>
        ) : runs.isLoading ? (
          <Loading />
        ) : (
          <RunTable items={runs.data?.items ?? []} />
        )}
      </section>
    </>
  );
}
