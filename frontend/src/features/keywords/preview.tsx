"use client";

import Link from "next/link";
import { type Schema, useApi } from "@/shared/api/client";
import { number, safeUrl } from "@/shared/lib/format";
import { Empty, ErrorNotice, Loading, State } from "@/shared/ui/feedback";

export function PreviewResult({ id }: { id: string }) {
  const request = useApi<Schema["RequestInfo"]>(`/collection-runs/${id}`);
  const items = useApi<Schema["ResultPage"]>(
    `/collection-runs/${id}/items?limit=10`,
  );
  if (request.error)
    return (
      <ErrorNotice error={request.error} retry={() => request.refetch()} />
    );
  if (!request.data) return <Loading />;
  const run = request.data;
  return (
    <div className="section-gap" aria-live="polite">
      <div className="button-row" style={{ justifyContent: "space-between" }}>
        <State value={run.status} />
        <Link href={`/runs/${id}`}>요청 상세</Link>
      </div>
      {["queued", "submitted"].includes(run.status) && (
        <div className="notice section-gap">
          <span>
            미리보기 요청을 접수했어요. 수집 환경이 연결되면 결과가 표시돼요.{" "}
            <Link href="/workers">수집 환경 확인</Link>
          </span>
        </div>
      )}
      {run.error && <ErrorNotice error={new Error(run.error)} />}
      {run.summary.total_count !== undefined && (
        <p className="section-gap">
          검색 결과{" "}
          <strong>{number(run.summary.total_count as number)}건</strong>{" "}
          <span className="hint">· 처음 10건 표시</span>
        </p>
      )}
      {items.error && (
        <ErrorNotice error={items.error} retry={() => items.refetch()} />
      )}
      <ul className="preview-list">
        {items.data?.items.map((item) => (
          <li key={item.source_id}>
            {safeUrl(item.original_url ?? item.url) ? (
              <a
                href={safeUrl(item.original_url ?? item.url)}
                target="_blank"
                rel="noreferrer"
              >
                {item.title}
              </a>
            ) : (
              <strong>{item.title}</strong>
            )}
            <p>{item.summary}</p>
          </li>
        ))}
      </ul>
      {run.status === "completed" &&
        !items.data?.items.length &&
        !items.isLoading &&
        !items.error && (
          <Empty title="검색 결과가 없어요">
            키워드나 기간을 바꿔 다시 확인해 보세요.
          </Empty>
        )}
    </div>
  );
}
