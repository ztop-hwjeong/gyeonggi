"use client";

import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import { type FormEvent, useState } from "react";
import { type Schema, useApi } from "@/shared/api/client";
import { dateTime, safeUrl, sourceNames } from "@/shared/lib/format";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
} from "@/shared/ui/feedback";

export function ResultList() {
  const [offset, setOffset] = useState(0),
    [source, setSource] = useState("");
  const [text, setText] = useState(""),
    [search, setSearch] = useState("");
  const params = new URLSearchParams({
    limit: "20",
    offset: String(offset),
    q: search,
  });
  if (source) params.set("source", source);
  const query = useApi<Schema["StoredArticlePage"]>(`/articles?${params}`);
  function submit(event: FormEvent) {
    event.preventDefault();
    setSearch(text);
    setOffset(0);
  }
  return (
    <>
      <PageHeading
        title="수집 결과"
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
                setSource(e.target.value);
                setOffset(0);
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
          <span className="hint">신규 저장순</span>
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
                  {safeUrl(item.original_url ?? item.url) ? (
                    <a
                      className="article-link"
                      href={safeUrl(item.original_url ?? item.url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {item.title}
                    </a>
                  ) : (
                    item.title
                  )}
                </h2>
                <p>{item.summary}</p>
              </li>
            ))}
          </ul>
        )}
        <Pager
          total={query.data?.total ?? 0}
          offset={offset}
          size={20}
          onChange={setOffset}
        />
      </section>
    </>
  );
}
