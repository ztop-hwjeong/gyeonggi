"use client";

import { DesktopIcon, PackageIcon } from "@phosphor-icons/react";
import { type Schema, useApi } from "@/shared/api/client";
import { dateTime } from "@/shared/lib/format";
import { Empty, ErrorNotice, Loading, PageHeading } from "@/shared/ui/feedback";

export function WorkerStatus() {
  const query = useApi<Schema["WorkerSnapshot"]>("/monitoring/workers");
  return (
    <>
      <PageHeading
        title="수집 환경"
        action={
          <button
            type="button"
            className="button secondary"
            disabled={query.isFetching}
            onClick={() => query.refetch()}
          >
            {query.isFetching ? "확인 중…" : "연결 상태 다시 확인"}
          </button>
        }
      />
      {query.error && (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      )}
      {query.error && !query.data ? null : query.isLoading ? (
        <Loading />
      ) : (
        <>
          <div className="worker-grid">
            {["docker-collector", "windows-collector"].map((name) => {
              const pool = query.data?.pools.find((p) => p.name === name),
                windows = name === "windows-collector";
              return (
                <section className="panel" key={name}>
                  <div className="panel-header">
                    <h2 className="button-row">
                      {windows ? (
                        <DesktopIcon size={23} />
                      ) : (
                        <PackageIcon size={23} />
                      )}
                      {windows ? "브라우저 수집" : "목록 수집"}
                    </h2>
                  </div>
                  <div className="panel-body">
                    <p className="hint">
                      {windows
                        ? "로그인이 필요한 원문 등 실제 브라우저로 확인하는 작업"
                        : "빅카인즈·네이버 검색 목록과 미리보기·기간 수집"}
                    </p>
                    {!pool ? (
                      <Empty title="연결 정보 없음" />
                    ) : (
                      <>
                        <p className="section-gap">
                          {pool.is_paused
                            ? "새 요청 처리 중지"
                            : pool.workers.some(
                                  (worker) => worker.status === "ONLINE",
                                )
                              ? "새 요청 처리 가능"
                              : "연결 대기 · 요청 처리 불가"}{" "}
                          · 연결{" "}
                          {
                            pool.workers.filter((w) => w.status === "ONLINE")
                              .length
                          }
                          대
                        </p>
                        {!pool.workers.some(
                          (worker) => worker.status === "ONLINE",
                        )
                          ? null
                          : pool.workers
                              .filter((worker) => worker.status === "ONLINE")
                              .map((worker, index) => (
                                <div className="worker-row" key={worker.id}>
                                  <div>
                                    <strong>
                                      연결된 수집 장치 {index + 1}
                                    </strong>
                                    <div className="table-sub">
                                      마지막 응답{" "}
                                      {dateTime(worker.last_heartbeat_time)}
                                    </div>
                                  </div>
                                  <span
                                    className={`state ${worker.status === "OFFLINE" ? "failed" : ""}`}
                                  >
                                    <span className="state-dot" />
                                    {worker.status === "ONLINE"
                                      ? "연결됨"
                                      : "연결 끊김"}
                                  </span>
                                </div>
                              ))}
                        {pool.workers.some(
                          (worker) => worker.status !== "ONLINE",
                        ) && (
                          <div className="technical-info section-gap">
                            <p>
                              연결되지 않은 장치{" "}
                              {
                                pool.workers.filter(
                                  (worker) => worker.status !== "ONLINE",
                                ).length
                              }
                              대
                            </p>
                            {pool.workers
                              .filter((worker) => worker.status !== "ONLINE")
                              .map((worker) => (
                                <p key={worker.id}>
                                  {worker.name} · 마지막 응답{" "}
                                  {dateTime(worker.last_heartbeat_time)}
                                </p>
                              ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
          <p className="hint section-gap">
            마지막 확인 {dateTime(query.data?.observed_at)}
          </p>
        </>
      )}
    </>
  );
}
