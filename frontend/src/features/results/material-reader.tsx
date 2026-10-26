"use client";

import { ArrowLeftIcon, ArrowSquareOutIcon } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { put, useApi } from "@/shared/api/client";
import { dateTime, safeUrl, sourceNames } from "@/shared/lib/format";
import { Empty, ErrorNotice, Loading } from "@/shared/ui/feedback";
import type {
  AnalysisTarget,
  ArticleTargetLink,
  MaterialDetail,
} from "../articles/types";

const kindLabels = {
  news: { content: "기사 내용", name: "언론사" },
  cafe: { content: "카페글 내용", name: "카페명" },
  blog: { content: "블로그글 내용", name: "블로그명" },
};

export function MaterialReader({
  materialId,
  returnQuery,
}: {
  materialId: string;
  returnQuery: string;
}) {
  const query = useApi<MaterialDetail>(
    materialId ? `/materials/${materialId}` : null,
    false,
  );
  const material = query.data;
  const targets = useApi<AnalysisTarget[]>(
    material?.kind === "news" ? "/analysis-targets" : null,
    false,
  );
  const targetLinks = useApi<ArticleTargetLink[]>(
    material?.kind === "news" ? `/articles/${material.id}/targets` : null,
    false,
  );
  const queryClient = useQueryClient();
  const refresh = async () => {
    await Promise.all([query.refetch(), targetLinks.refetch()]);
    await queryClient.invalidateQueries({
      predicate: ({ queryKey }) =>
        typeof queryKey[0] === "string" &&
        (queryKey[0].startsWith("/articles") ||
          queryKey[0].startsWith("/materials")),
    });
  };
  const back = `/results${returnQuery ? `?${new URLSearchParams(returnQuery)}` : ""}`;
  return (
    <>
      <Link className="back-link" href={back}>
        <ArrowLeftIcon size={16} />
        수집 자료로 돌아가기
      </Link>
      {query.error ? (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      ) : !material ? (
        <Loading />
      ) : (
        <article className="panel panel-body article-reader">
          <div className="article-meta">
            <span>{kindLabels[material.kind].name}</span>
            <span>{materialName(material)}</span>
            <span>{dateTime(material.published_at)}</span>
          </div>
          <h1>{material.title}</h1>
          <div className="context-actions section-gap">
            {materialLink(material) && (
              <a
                className="button secondary"
                href={materialLink(material)}
                target="_blank"
                rel="noreferrer"
              >
                {kindLabels[material.kind].name}{" "}
                <ArrowSquareOutIcon size={17} />
              </a>
            )}
            {material.sources.map((source) => {
              const url = safeUrl(source.original_url ?? source.url);
              return url ? (
                <a
                  key={`${source.source}:${source.source_id}`}
                  className="button secondary"
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {sourceNames[source.source] ?? "수집처"}{" "}
                  <ArrowSquareOutIcon size={17} />
                </a>
              ) : null;
            })}
          </div>
          <section className="article-summary">
            <h2>{kindLabels[material.kind].content}</h2>
            <p>{material.content_preview || "—"}</p>
          </section>
          <section className="section-gap">
            <h2>본문</h2>
            {material.body ? (
              <p className="article-body">{material.body}</p>
            ) : (
              <Empty title="본문이 없어요" />
            )}
          </section>
          {material.kind === "news" && (
            <ArticleControls
              articleId={material.id}
              targets={targets.data ?? []}
              links={targetLinks.data ?? []}
              refresh={refresh}
            />
          )}
        </article>
      )}
    </>
  );
}

function materialName(material: MaterialDetail) {
  if (material.kind === "news") return material.publisher ?? "—";
  if (material.kind === "cafe") return material.cafe_name ?? "—";
  return material.blog_name ?? "—";
}

function materialLink(material: MaterialDetail) {
  if (material.kind === "cafe") return safeUrl(material.cafe_url);
  if (material.kind === "blog") return safeUrl(material.blog_url);
  return undefined;
}

function ArticleControls({
  articleId,
  targets,
  links,
  refresh,
}: {
  articleId: string;
  targets: AnalysisTarget[];
  links: ArticleTargetLink[];
  refresh: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function saveInclusion(decision: "include" | "exclude") {
    if (!reason.trim()) {
      setError("판단 사유를 적어 주세요.");
      return;
    }
    try {
      await put(`/articles/${articleId}/inclusion`, { decision, reason });
      await refresh();
      setError("");
      setMessage("저장됐어요.");
    } catch (writeError) {
      setError(
        writeError instanceof Error ? writeError.message : "저장하지 못했어요.",
      );
    }
  }
  return (
    <section className="section-gap article-controls">
      <h2>분석 포함</h2>
      <textarea
        aria-label="포함 또는 제외 사유"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="판단 사유"
      />
      <div className="button-row">
        <button
          className="button"
          type="button"
          onClick={() => saveInclusion("include")}
        >
          포함
        </button>
        <button
          className="button secondary"
          type="button"
          onClick={() => saveInclusion("exclude")}
        >
          제외
        </button>
        {message && <span role="status">{message}</span>}
        {error && <span role="alert">{error}</span>}
      </div>
      <h2 className="section-gap">분석 대상</h2>
      <div className="target-list">
        {targets.map((target) => {
          const link = links.find((item) => item.target_id === target.id);
          return (
            <div key={target.id}>
              <span>{target.name}</span>
              <div className="button-row">
                <button
                  className="button quiet"
                  type="button"
                  onClick={() =>
                    saveTarget(
                      articleId,
                      target.id,
                      "include",
                      refresh,
                      setError,
                    )
                  }
                >
                  포함
                </button>
                <button
                  className="button quiet"
                  type="button"
                  onClick={() =>
                    saveTarget(
                      articleId,
                      target.id,
                      "exclude",
                      refresh,
                      setError,
                    )
                  }
                >
                  제외
                </button>
                <span>
                  {link?.decision === "include"
                    ? "포함"
                    : link?.decision === "exclude"
                      ? "제외"
                      : "미지정"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

async function saveTarget(
  articleId: string,
  targetId: string,
  decision: "include" | "exclude",
  refresh: () => Promise<void>,
  setError: (value: string) => void,
) {
  try {
    await put(`/articles/${articleId}/targets/${targetId}`, {
      decision,
      reason: `분석 대상으로 ${decision === "include" ? "포함" : "제외"}`,
    });
    await refresh();
    setError("");
  } catch (writeError) {
    setError(
      writeError instanceof Error ? writeError.message : "저장하지 못했어요.",
    );
  }
}
