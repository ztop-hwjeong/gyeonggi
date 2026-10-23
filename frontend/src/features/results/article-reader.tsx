"use client";

import { ArrowLeftIcon, ArrowSquareOutIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { type Schema, useApi } from "@/shared/api/client";
import { dateTime, safeUrl, sourceNames } from "@/shared/lib/format";
import { Empty, ErrorNotice, Loading } from "@/shared/ui/feedback";

export function ArticleReader({
  source,
  sourceId,
  returnQuery,
}: {
  source: string;
  sourceId: string;
  returnQuery: string;
}) {
  const query = useApi<Schema["StoredArticleDetail"]>(
    `/articles/detail?${new URLSearchParams({ source, source_id: sourceId })}`,
    false,
  );
  const back = `/results${returnQuery ? `?${new URLSearchParams(returnQuery)}` : ""}`;
  const article = query.data;
  return (
    <>
      <Link className="back-link" href={back}>
        <ArrowLeftIcon size={16} />
        수집 자료로 돌아가기
      </Link>
      {query.error ? (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      ) : !article ? (
        <Loading />
      ) : (
        <article className="panel panel-body article-reader">
          <div className="article-meta">
            <span>{sourceNames[article.source]}</span>
            <span>{article.publisher ?? "발행처 정보 없음"}</span>
            <span>
              {article.published_on ?? dateTime(article.published_at)}
            </span>
          </div>
          <h1>{article.title}</h1>
          <div className="context-actions section-gap">
            {safeUrl(article.original_url ?? article.url) && (
              <a
                className="button secondary"
                href={safeUrl(article.original_url ?? article.url)}
                target="_blank"
                rel="noreferrer"
              >
                원문 새 창에서 보기 <ArrowSquareOutIcon size={17} />
              </a>
            )}
            <span className="hint">
              {article.has_body
                ? `본문 수집 ${dateTime(article.body_collected_at)}`
                : "검색 목록만 확보"}
            </span>
          </div>
          <section className="article-summary">
            <h2>검색 요약</h2>
            <p>{article.summary || "제공된 검색 요약이 없어요."}</p>
          </section>
          <section className="section-gap">
            <h2>수집한 본문</h2>
            {article.body ? (
              <p className="article-body">{article.body}</p>
            ) : (
              <Empty title="아직 수집한 본문이 없어요">
                검색 요약은 본문 전체가 아니에요. 원문 링크에서 내용을 확인해
                주세요.
              </Empty>
            )}
          </section>
        </article>
      )}
    </>
  );
}
