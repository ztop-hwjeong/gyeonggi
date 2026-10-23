"use client";

import { PlusIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useState } from "react";
import { type Schema, useApi } from "@/shared/api/client";
import { ErrorNotice, Loading, PageHeading, Pager } from "@/shared/ui/feedback";
import { RunTable } from "./run-table";

export function RunList() {
  const [offset, setOffset] = useState(0);
  const query = useApi<Schema["RequestPage"]>(
    `/collection-runs?limit=20&offset=${offset}`,
  );
  return (
    <>
      <PageHeading
        title="수집 실행"
        description="미리보기와 수집 요청의 진행 상황을 확인하고 기간 수집을 요청해요."
        action={
          <Link href="/runs/new" className="button">
            <PlusIcon size={18} />
            수집 요청
          </Link>
        }
      />
      {query.error && (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      )}
      <section className="panel">
        {query.error && !query.data ? null : query.isLoading ? (
          <Loading />
        ) : (
          <>
            <RunTable items={query.data?.items ?? []} />
            <Pager
              total={query.data?.total ?? 0}
              offset={offset}
              size={20}
              onChange={setOffset}
            />
          </>
        )}
      </section>
    </>
  );
}
