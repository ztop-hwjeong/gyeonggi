"use client";
import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import { useState } from "react";
import { type Schema, useIdempotentPost } from "@/shared/api/client";
import { sourceNames, today } from "@/shared/lib/format";
import { ErrorNotice } from "@/shared/ui/feedback";
import { PreviewResult } from "./preview";

export function KeywordPreview({
  definition,
}: {
  definition: Schema["RuleDefinition"];
}) {
  const createPreview = useIdempotentPost<Schema["RequestInfo"]>();
  const { sources } = definition;
  const [previewSource, setPreviewSource] = useState<Schema["SourceCode"]>(
    sources[0],
  );
  const actualSource = sources.includes(previewSource)
    ? previewSource
    : sources[0];
  const [start, setStart] = useState(today),
    [end, setEnd] = useState(today);
  const [pending, setPending] = useState<"preview" | null>(null);
  const [error, setError] = useState<Error>();
  const [requestId, setRequestId] = useState<string>();
  const [previewSnapshot, setPreviewSnapshot] = useState("");
  const fingerprint = JSON.stringify([
    definition.terms,
    actualSource,
    actualSource === "bigkinds" ? [start, end] : [],
  ]);
  async function preview() {
    setPending("preview");
    setError(undefined);
    try {
      if (!sources.length || !definition.terms.length)
        throw new Error("키워드와 채널을 하나 이상 선택해 주세요.");
      if (definition.terms.length > 10)
        throw new Error("키워드는 최대 10개까지 입력해 주세요.");
      if (actualSource === "bigkinds" && (!start || !end || start > end))
        throw new Error("미리보기 시작일과 종료일을 확인해 주세요.");
      const result = await createPreview("/collection-previews", {
        definition: {
          ...definition,
          name: definition.name || "키워드 미리보기",
        },
        source: actualSource,
        start_date: actualSource === "bigkinds" ? start : today(),
        end_date: actualSource === "bigkinds" ? end : today(),
      });
      setRequestId(result.id);
      setPreviewSnapshot(fingerprint);
    } catch (error) {
      setError(
        error instanceof Error
          ? error
          : new Error("미리보기를 요청하지 못했어요."),
      );
    } finally {
      setPending(null);
    }
  }
  return (
    <section className="panel">
      <div className="panel-body">
        <h2>검색 결과 미리보기</h2>
        {error && <ErrorNotice error={error} />}
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
        {requestId && (
          <>
            {previewSnapshot !== fingerprint && (
              <div className="notice warning section-gap">
                입력 조건이 바뀌었어요. 아래는 이전 조건의 결과예요. 현재
                조건으로 미리보기를 다시 실행해 주세요.
              </div>
            )}
            <PreviewResult id={requestId} />
          </>
        )}
      </div>
    </section>
  );
}
