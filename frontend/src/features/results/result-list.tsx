"use client";

import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { type Schema, useApi } from "@/shared/api/client";
import { dateTime, safeUrl, sourceNames } from "@/shared/lib/format";
import { useListLocation } from "@/shared/lib/list-location";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
} from "@/shared/ui/feedback";

export function ResultList() {
  const { params: location, offset, update } = useListLocation();
  const source = location.get("source") ?? "";
  const search = location.get("q") ?? "";
  const [text, setText] = useState(search);
  useEffect(() => setText(search), [search]);
  const params = new URLSearchParams({
    limit: "20",
    offset: String(offset),
    q: search,
  });
  if (source) params.set("source", source);
  const query = useApi<Schema["StoredArticlePage"]>(`/articles?${params}`);
  function submit(event: FormEvent) {
    event.preventDefault();
    update({ q: text });
  }
  return (
    <>
      <PageHeading
        title="수집 자료"
        description="채널별로 저장한 목록을 찾아보고 원문과 본문 확보 여부를 확인해요."
      />
      {query.error && (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      )}
      <section className="panel">
        <div className="toolbar">
          <form className="filters" onSubmit={submit}>
            <label className="sr-only" htmlFor="result-channel">
              수집 채널
            </label>
            <select
              id="result-channel"
              value={source}
              onChange={(e) => {
                update({ source: e.target.value });
              }}
            >
              <option value="">전체 채널</option>
              {Object.entries(sourceNames).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="result-search">
              제목·요약 검색
            </label>
            <input
              id="result-search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="제목·요약 검색"
              maxLength={100}
            />
            <button className="button secondary" type="submit">
              <MagnifyingGlassIcon size={17} />
              검색
            </button>
          </form>
          <div className="button-row">
            {(search || source) && (
              <Link className="button quiet" href="/results">
                조건 초기화
              </Link>
            )}
            <span className="hint">새로 저장한 자료부터</span>
          </div>
        </div>
        {query.error && !query.data ? null : query.isLoading ? (
          <Loading />
        ) : !query.data?.items.length ? (
          <Empty
            title={
              search || source
                ? "조건에 맞는 자료가 없어요"
                : "아직 수집된 자료가 없어요"
            }
          >
            {search || source
              ? "채널이나 검색어를 바꿔 확인해 보세요."
              : "키워드를 등록하고 수집을 요청하면 자료가 쌓여요."}
          </Empty>
        ) : (
          <ul className="article-list">
            {query.data.items.map((item) => (
              <li key={`${item.source}:${item.source_id}`}>
                <div className="article-meta">
                  <span>{sourceNames[item.source]}</span>
                  <span>{item.publisher ?? "검색 목록"}</span>
                  <span>
                    {item.published_on ?? dateTime(item.published_at)}
                  </span>
                  <span>
                    {item.has_body ? "본문 확보" : "목록 확보 · 본문 미수집"}
                  </span>
                </div>
                <h2>
                  <Link
                    className="article-link"
                    href={`/results/read?${new URLSearchParams({ source: item.source, source_id: item.source_id, return_query: location.toString() })}`}
                  >
                    {item.title}
                  </Link>
                </h2>
                <p>{item.summary}</p>
                {safeUrl(item.original_url ?? item.url) && (
                  <a
                    className="source-link"
                    href={safeUrl(item.original_url ?? item.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    원문 새 창에서 보기
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
        <Pager
          total={query.data?.total ?? 0}
          offset={offset}
          size={20}
          onChange={(offset) => update({ offset })}
        />
      </section>
    </>
  );
}
