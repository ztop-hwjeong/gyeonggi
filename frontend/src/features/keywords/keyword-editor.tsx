"use client";

import {
  ArrowLeftIcon,
  FloppyDiskIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import {
  api,
  type Schema,
  useApi,
  useIdempotentPost,
} from "@/shared/api/client";
import { sourceNames, today } from "@/shared/lib/format";
import { ErrorNotice, Loading, PageHeading } from "@/shared/ui/feedback";
import { PreviewResult } from "./preview";

type Definition = Schema["RuleDefinition"];

export function KeywordEditor({ id }: { id?: string }) {
  const rule = useApi<Schema["RuleInfo"]>(
    id ? `/keyword-rules/${id}` : null,
    false,
  );
  if (id && rule.error)
    return <ErrorNotice error={rule.error} retry={() => rule.refetch()} />;
  if (id && !rule.data) return <Loading />;
  return <EditorForm rule={rule.data} />;
}

function EditorForm({ rule }: { rule?: Schema["RuleInfo"] }) {
  const createPreview = useIdempotentPost<Schema["RequestInfo"]>();
  const router = useRouter(),
    cache = useQueryClient();
  const [name, setName] = useState(rule?.definition.name ?? "");
  const [description, setDescription] = useState(
    rule?.definition.description ?? "",
  );
  const [terms, setTerms] = useState(rule?.definition.terms.join("\n") ?? "");
  const [sources, setSources] = useState<Definition["sources"]>(
    rule?.definition.sources ?? ["bigkinds"],
  );
  const [enabled, setEnabled] = useState(rule?.definition.enabled ?? false);
  const [interval, setInterval] = useState(
    rule?.definition.interval_minutes ?? 15,
  );
  const [previewSource, setPreviewSource] = useState<Schema["SourceCode"]>(
    sources[0],
  );
  const [start, setStart] = useState(today),
    [end, setEnd] = useState(today);
  const [requestId, setRequestId] = useState<string>();
  const [pending, setPending] = useState<"save" | "preview" | null>(null);
  const [error, setError] = useState<Error>();
  const definition: Definition = {
    name,
    description,
    terms: terms
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean),
    sources,
    enabled,
    interval_minutes: interval,
  };
  const actualSource = sources.includes(previewSource)
    ? previewSource
    : sources[0];

  async function save(event: FormEvent) {
    event.preventDefault();
    setPending("save");
    setError(undefined);
    try {
      if (!sources.length || !definition.terms.length)
        throw new Error("키워드와 채널을 하나 이상 선택해 주세요.");
      await api<Schema["RuleInfo"]>(
        rule ? `/keyword-rules/${rule.id}` : "/keyword-rules",
        {
          method: rule ? "PUT" : "POST",
          body: JSON.stringify(
            rule ? { ...definition, version: rule.version } : definition,
          ),
        },
      );
      await cache.invalidateQueries();
      router.push("/keywords");
    } catch (e) {
      setError(e instanceof Error ? e : new Error("저장하지 못했어요."));
    } finally {
      setPending(null);
    }
  }

  async function preview() {
    setPending("preview");
    setError(undefined);
    try {
      if (!sources.length || !definition.terms.length)
        throw new Error("키워드와 채널을 하나 이상 선택해 주세요.");
      const result = await createPreview("/collection-previews", {
        definition: { ...definition, name: name || "키워드 미리보기" },
        source: actualSource,
        start_date: actualSource === "bigkinds" ? start : today(),
        end_date: actualSource === "bigkinds" ? end : today(),
      });
      setRequestId(result.id);
      await cache.invalidateQueries({ queryKey: ["/collection-runs?limit=5"] });
    } catch (e) {
      setError(
        e instanceof Error ? e : new Error("미리보기를 요청하지 못했어요."),
      );
    } finally {
      setPending(null);
    }
  }

  return (
    <>
      <Link className="back-link" href="/keywords">
        <ArrowLeftIcon size={16} />
        키워드 관리
      </Link>
      <PageHeading
        title={rule ? "검색 규칙 수정" : "새 검색 규칙"}
        description="같은 주제의 키워드를 묶고, 수집 전에 검색 결과를 확인해 보세요."
      />
      {error && <ErrorNotice error={error} />}
      <div className="editor-grid">
        <form className="panel" onSubmit={save}>
          <section className="form-section">
            <h2>검색 조건</h2>
            <div className="form-stack">
              <div className="field">
                <label htmlFor="rule-name">규칙 이름</label>
                <input
                  id="rule-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="예: 교권 보호 정책"
                  required
                  maxLength={100}
                />
              </div>
              <div className="field">
                <label htmlFor="rule-description">
                  설명 <span className="muted">(선택)</span>
                </label>
                <input
                  id="rule-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="어떤 내용을 살펴보는 규칙인가요?"
                  maxLength={500}
                />
              </div>
              <div className="field">
                <label htmlFor="rule-terms">검색 키워드</label>
                <textarea
                  id="rule-terms"
                  value={terms}
                  onChange={(e) => setTerms(e.target.value)}
                  placeholder={"교권보호\n교권 보호"}
                  required
                  aria-describedby="terms-help"
                />
                <p id="terms-help" className="hint">
                  한 줄에 하나씩, 최대 10개를 입력해 주세요. 하나라도 포함된
                  자료를 검색해요.
                </p>
              </div>
              <fieldset className="field">
                <legend>수집 채널</legend>
                <div className="check-list">
                  {Object.entries(sourceNames).map(([code, label]) => (
                    <label key={code}>
                      <input
                        type="checkbox"
                        checked={sources.includes(code as Schema["SourceCode"])}
                        onChange={(e) =>
                          setSources(
                            e.target.checked
                              ? [...sources, code as Schema["SourceCode"]]
                              : sources.filter((s) => s !== code),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </fieldset>
            </div>
          </section>
          <section className="form-section">
            <h2>정기 수집</h2>
            <div className="form-stack">
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                정기 수집 사용
              </label>
              <div className="field">
                <label htmlFor="rule-interval">수집 주기</label>
                <select
                  id="rule-interval"
                  value={interval}
                  onChange={(e) => setInterval(Number(e.target.value))}
                >
                  {[15, 30, 60, 180, 1440].map((value) => (
                    <option key={value} value={value}>
                      {value >= 60 ? `${value / 60}시간` : `${value}분`}마다
                    </option>
                  ))}
                </select>
              </div>
              <p className="hint">
                저장 후 활성 규칙부터 수집해요. 키워드 수정은 이후 요청에
                적용되며, 과거 자료는 별도로 기간 수집을 요청해 주세요.
              </p>
            </div>
          </section>
          <div className="form-actions">
            <Link href="/keywords" className="button secondary">
              취소
            </Link>
            <button
              type="submit"
              className="button"
              disabled={pending !== null}
            >
              <FloppyDiskIcon size={18} />
              {pending === "save" ? "저장 중…" : "규칙 저장"}
            </button>
          </div>
        </form>
        <section className="panel">
          <div className="panel-body">
            <h2>검색 결과 미리보기</h2>
            <p className="hint" style={{ marginTop: 8, marginBottom: 24 }}>
              현재 입력한 조건으로 확인해요. 정식 수집 자료나 마지막 수집 위치는
              바뀌지 않아요.
            </p>
            <div className="form-stack">
              <div className="field">
                <label htmlFor="preview-source">미리보기 채널</label>
                <select
                  id="preview-source"
                  value={actualSource ?? ""}
                  onChange={(e) =>
                    setPreviewSource(e.target.value as Schema["SourceCode"])
                  }
                >
                  {sources.map((source) => (
                    <option key={source} value={source}>
                      {sourceNames[source]}
                    </option>
                  ))}
                </select>
              </div>
              {actualSource === "bigkinds" ? (
                <div className="field-grid">
                  <div className="field">
                    <label htmlFor="preview-start">시작일</label>
                    <input
                      id="preview-start"
                      type="date"
                      value={start}
                      max={end}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="preview-end">종료일</label>
                    <input
                      id="preview-end"
                      type="date"
                      value={end}
                      min={start}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </div>
                </div>
              ) : (
                <p className="hint">
                  네이버는 기간 검색 대신 최신 검색 결과를 확인해요.
                </p>
              )}
              <button
                type="button"
                className="button secondary"
                disabled={pending !== null || !sources.length}
                onClick={preview}
              >
                <MagnifyingGlassIcon size={18} />
                {pending === "preview" ? "요청 중…" : "미리보기 실행"}
              </button>
            </div>
            {requestId && <PreviewResult id={requestId} />}
          </div>
        </section>
      </div>
    </>
  );
}
