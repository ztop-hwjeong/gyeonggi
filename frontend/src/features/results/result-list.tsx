"use client";

import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { useApi } from "@/shared/api/client";
import { useListLocation } from "@/shared/lib/list-location";
import { Empty, ErrorNotice, Loading, Pager } from "@/shared/ui/feedback";
import type {
  AnalysisTarget,
  ArticlePage,
  MaterialKind,
  MaterialPage,
} from "../articles/types";
import { TagFolderPanel } from "./tag-folder-panel";

const tabs: { value: "all" | MaterialKind; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "news", label: "기사" },
  { value: "blog", label: "블로그글" },
];

function mediaName(item: {
  kind: MaterialKind;
  publisher?: string | null;
  blog_name?: string | null;
}) {
  if (item.kind === "news") return item.publisher ?? "—";
  return item.blog_name ?? "—";
}

function kindName(kind: MaterialKind) {
  return { news: "기사", blog: "블로그글" }[kind];
}

export function ResultList() {
  const { params: location, offset, update } = useListLocation();
  const kind = (location.get("kind") ?? "all") as "all" | MaterialKind;
  const search = location.get("q") ?? "";
  const inclusion = location.get("inclusion") ?? "all";
  const targetId = location.get("target_id") ?? "";
  const tagId = location.get("tag_id") ?? "";
  const folderId = location.get("folder_id") ?? "";
  const unfiled = location.get("unfiled") === "true";
  const news = kind === "news";
  const scopeSelected = Boolean(tagId) || Boolean(folderId) || unfiled;
  const [text, setText] = useState(search);
  useEffect(() => setText(search), [search]);
  const params = new URLSearchParams({
    limit: "20",
    offset: String(offset),
    q: search,
  });
  if (news && inclusion !== "all") params.set("inclusion", inclusion);
  if (news && targetId) params.set("target_id", targetId);
  if (kind !== "all") params.set("kind", kind);
  if (tagId) params.set("tag_id", tagId);
  if (unfiled) params.set("unfiled", "true");
  if (folderId) {
    params.set("folder_id", folderId);
    params.set("include_descendants", "true");
  }
  const articleFilter =
    news && (inclusion !== "all" || Boolean(targetId) || scopeSelected);
  const articleParams = new URLSearchParams({
    limit: "20",
    offset: String(offset),
    q: search,
  });
  if (inclusion !== "all") articleParams.set("inclusion", inclusion);
  if (targetId) articleParams.set("target_id", targetId);
  if (tagId) articleParams.set("tag_id", tagId);
  if (unfiled) articleParams.set("unfiled", "true");
  if (folderId) {
    articleParams.set("folder_id", folderId);
    articleParams.set("include_descendants", "true");
  }
  const materialQuery = useApi<MaterialPage>(
    articleFilter ? null : `/materials?${params}`,
  );
  const articleQuery = useApi<ArticlePage>(
    articleFilter ? `/articles?${articleParams}` : null,
  );
  const query = articleFilter ? articleQuery : materialQuery;
  const targets = useApi<AnalysisTarget[]>("/analysis-targets", false);
  function submit(event: FormEvent) {
    event.preventDefault();
    update({ q: text });
  }
  return (
    <div className="results-page">
      {query.error && (
        <ErrorNotice error={query.error} retry={() => query.refetch()} />
      )}
      <section className="panel">
        <div className="material-tabs" role="tablist" aria-label="자료 유형">
          {tabs.map((tab) => (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={kind === tab.value}
              className={kind === tab.value ? "active" : ""}
              onClick={() =>
                update({
                  kind: tab.value === "all" ? null : tab.value,
                  inclusion: null,
                  target_id: null,
                  source: null,
                })
              }
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="article-workspace">
          {
            <TagFolderPanel
              folderId={folderId}
              tagId={tagId}
              unfiled={unfiled}
              kind={kind}
              onChange={(values) =>
                update({
                  q: null,
                  source: null,
                  inclusion: null,
                  target_id: null,
                  offset: 0,
                  ...values,
                })
              }
            />
          }
          <div className="result-list-content">
            <div className="toolbar">
              <form className="filters" onSubmit={submit}>
                {news && (
                  <>
                    <select
                      aria-label="분석 포함 상태"
                      value={inclusion}
                      onChange={(e) => update({ inclusion: e.target.value })}
                    >
                      <option value="all">전체 자료</option>
                      <option value="included">분석 포함</option>
                      <option value="excluded">분석 제외</option>
                    </select>
                    <select
                      aria-label="분석 대상"
                      value={targetId}
                      onChange={(e) => update({ target_id: e.target.value })}
                    >
                      <option value="">분석 대상 전체</option>
                      {targets.data?.map((target) => (
                        <option key={target.id} value={target.id}>
                          {target.name}
                        </option>
                      ))}
                    </select>
                  </>
                )}
                <input
                  aria-label="자료 검색"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="제목·내용 검색"
                  maxLength={100}
                />
                <button className="button secondary" type="submit">
                  <MagnifyingGlassIcon size={17} />
                  검색
                </button>
              </form>
              {news && (
                <Link className="button quiet" href="/analysis-targets">
                  기사 분석 대상
                </Link>
              )}
              {(search || (news && (inclusion !== "all" || targetId))) && (
                <Link className="button quiet" href="/results">
                  조건 초기화
                </Link>
              )}
            </div>
            {query.error && !query.data ? null : query.isLoading ? (
              <Loading />
            ) : !query.data?.items.length ? (
              <Empty title="조건에 맞는 자료가 없어요" />
            ) : (
              <div className="table-wrap">
                <table className="article-table">
                  <thead>
                    <tr>
                      <th>구분</th>
                      <th>매체·채널명</th>
                      <th>제목</th>
                      <th>내용</th>
                      <th>요약</th>
                    </tr>
                  </thead>
                  <tbody>
                    {query.data.items.map((item) => {
                      const itemKind: MaterialKind =
                        "kind" in item ? item.kind : "news";
                      return (
                        <tr key={item.id}>
                          <td>{kindName(itemKind)}</td>
                          <td>{mediaName({ ...item, kind: itemKind })}</td>
                          <td>
                            <Link
                              className="article-link"
                              href={`/results/read?${new URLSearchParams({ material_id: item.id, return_query: location.toString() })}`}
                            >
                              {item.title}
                            </Link>
                          </td>
                          <td>{item.content_preview || "—"}</td>
                          <td>{item.summary || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <Pager
              total={query.data?.total ?? 0}
              offset={offset}
              size={20}
              onChange={(next) => update({ offset: next })}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
