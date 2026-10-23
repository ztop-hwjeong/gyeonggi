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
        title="실행 환경"
        description="Docker 수집과 Windows 브라우저 수집의 연결 상태를 확인해요."
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
                      {windows ? "Windows Worker" : "Docker Worker"}
                    </h2>
                  </div>
                  <div className="panel-body">
                    <p className="hint">
                      {windows
                        ? "실제 Edge가 필요한 브라우저 수집"
                        : "브라우저 없이 처리하는 목록·원문 수집"}
                    </p>
                    {!pool ? (
                      <Empty title="등록된 실행 환경이 없어요">
                        Prefect의 work pool 등록 상태를 확인해 주세요.
                      </Empty>
                    ) : (
                      <>
                        <p className="section-gap">
                          {pool.is_paused
                            ? "작업 배정 일시 중지"
                            : "작업 배정 사용"}{" "}
                          · 연결{" "}
                          {
                            pool.workers.filter((w) => w.status === "ONLINE")
                              .length
                          }
                          대
                        </p>
                        {pool.workers.length === 0 ? (
                          <Empty title="연결된 Worker가 없어요">
                            Worker가 연결되면 대기 중인 요청을 실행해요.
                          </Empty>
                        ) : (
                          pool.workers.map((worker) => (
                            <div className="worker-row" key={worker.id}>
                              <div>
                                <strong>{worker.name}</strong>
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
                      </>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
          <p className="hint section-gap">
            Worker 연결과 실제 사이트 접근 성공은 별개예요. 요청별 수집 오류는
            수집 실행에서 확인해 주세요. 마지막 조회{" "}
            {dateTime(query.data?.observed_at)}
          </p>
        </>
      )}
    </>
  );
}
