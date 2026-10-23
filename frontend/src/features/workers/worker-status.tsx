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
        description="요청을 처리할 수 있는지 확인해요. 연결 문제가 계속되면 운영 담당자에게 알려 주세요."
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
                      <Empty title="등록된 수집 환경이 없어요">
                        운영 담당자에게 수집 환경 등록을 요청해 주세요.
                      </Empty>
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
                        ) ? (
                          <Empty title="수집 환경이 연결되지 않았어요">
                            접수한 요청은 대기해요. 운영 담당자에게 연결 확인을
                            요청해 주세요.
                          </Empty>
                        ) : (
                          pool.workers
                            .filter((worker) => worker.status === "ONLINE")
                            .map((worker, index) => (
                              <div className="worker-row" key={worker.id}>
                                <div>
                                  <strong>연결된 수집 장치 {index + 1}</strong>
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
                            ))
                        )}
                        {pool.workers.some(
                          (worker) => worker.status !== "ONLINE",
                        ) && (
                          <details className="technical-details section-gap">
                            <summary>
                              연결되지 않은 장치{" "}
                              {
                                pool.workers.filter(
                                  (worker) => worker.status !== "ONLINE",
                                ).length
                              }
                              대
                            </summary>
                            <p>
                              이전에 사용한 장치가 포함될 수 있어요. 현재 수집
                              가능 여부는 연결된 장치를 기준으로 확인해 주세요.
                            </p>
                            {pool.workers
                              .filter((worker) => worker.status !== "ONLINE")
                              .map((worker) => (
                                <p key={worker.id}>
                                  {worker.name} · 마지막 응답{" "}
                                  {dateTime(worker.last_heartbeat_time)}
                                </p>
                              ))}
                          </details>
                        )}
                      </>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
          <p className="hint section-gap">
            연결되어 있어도 사이트 응답에 따라 수집이 중단될 수 있어요. 요청별
            오류는 수집 이력에서 확인해 주세요. 마지막 조회{" "}
            {dateTime(query.data?.observed_at)}
          </p>
        </>
      )}
    </>
  );
}
