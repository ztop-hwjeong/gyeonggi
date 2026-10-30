"use client";

import { ArrowLeftIcon, FloppyDiskIcon } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";
import type { AnalysisTarget } from "@/features/articles/types";
import { api, put, type Schema, useApi } from "@/shared/api/client";
import { sourceNames } from "@/shared/lib/format";
import { useUnsavedChanges } from "@/shared/lib/unsaved-changes";
import { ErrorNotice, Loading, PageHeading } from "@/shared/ui/feedback";
import { KeywordPreview } from "./keyword-preview";

type Definition = Schema["RuleDefinition"];

const targetKindNames = {
  policy: "정책",
  regular: "정기 분석",
  current_issue: "현안 분석",
  leader_message: "기관장 메시지",
} as const;

export function KeywordEditor({ id }: { id?: string }) {
  const params = useSearchParams();
  const rule = useApi<Schema["RuleInfo"]>(
    id ? `/keyword-rules/${id}` : null,
    false,
  );
  if (id && rule.error)
    return <ErrorNotice error={rule.error} retry={() => rule.refetch()} />;
  if (id && !rule.data) return <Loading />;
  return (
    <EditorForm rule={rule.data} initiallySaved={params.get("saved") === "1"} />
  );
}

function EditorForm({
  rule,
  initiallySaved,
}: {
  rule?: Schema["RuleInfo"];
  initiallySaved: boolean;
}) {
  const router = useRouter(),
    cache = useQueryClient();
  const [activeRule, setActiveRule] = useState(rule);
  const [name, setName] = useState(rule?.definition.name ?? "");
  const [description, setDescription] = useState(
    rule?.definition.description ?? "",
  );
  const [terms, setTerms] = useState(rule?.definition.terms.join("\n") ?? "");
  const [sources, setSources] = useState<Definition["sources"]>(
    rule?.definition.sources ?? ["bigkinds"],
  );
  const [enabled, setEnabled] = useState(rule?.definition.enabled ?? false);
  const targets = useApi<AnalysisTarget[]>("/analysis-targets", false);
  const ruleTargets = useApi<{ target_ids: string[] }>(
    activeRule ? `/keyword-rules/${activeRule.id}/targets` : null,
    false,
  );
  const [targetIds, setTargetIds] = useState<string[]>([]);
  useEffect(() => {
    if (ruleTargets.data) setTargetIds(ruleTargets.data.target_ids);
  }, [ruleTargets.data]);
  const [mappingNeedsRetry, setMappingNeedsRetry] = useState(false);
  const targetMappingReady =
    !activeRule || Boolean(ruleTargets.data) || mappingNeedsRetry;
  const [pending, setPending] = useState<"save" | null>(null);
  const [error, setError] = useState<Error>();
  const [saved, setSaved] = useState(initiallySaved);
  const [baseline, setBaseline] = useState(
    JSON.stringify(
      rule?.definition ?? {
        name: "",
        description: "",
        terms: [],
        sources: ["bigkinds"],
        enabled: false,
      },
    ),
  );
  const definition: Definition = {
    name,
    description,
    terms: terms
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean),
    sources,
    enabled,
  };
  const dirty =
    JSON.stringify(definition) !== baseline ||
    JSON.stringify(targetIds) !==
      JSON.stringify(ruleTargets.data?.target_ids ?? []);
  useUnsavedChanges(dirty);
  const versions = useApi<Schema["RuleVersion"][]>(
    activeRule ? `/keyword-rules/${activeRule.id}/versions` : null,
    false,
  );

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!targetMappingReady) {
      setError(new Error("기존 분석 대상 연결을 확인한 뒤 저장해 주세요."));
      return;
    }
    setPending("save");
    setError(undefined);
    try {
      if (!sources.length || !definition.terms.length)
        throw new Error("키워드와 채널을 하나 이상 선택해 주세요.");
      if (definition.terms.length > 10)
        throw new Error("키워드는 최대 10개까지 입력해 주세요.");
      const result = mappingNeedsRetry
        ? activeRule
        : await api<Schema["RuleInfo"]>(
            activeRule ? `/keyword-rules/${activeRule.id}` : "/keyword-rules",
            {
              method: activeRule ? "PUT" : "POST",
              body: JSON.stringify(
                activeRule
                  ? { ...definition, version: activeRule.version }
                  : definition,
              ),
            },
          );
      if (!result) throw new Error("저장한 검색 조건을 찾지 못했어요.");
      setActiveRule(result);
      setName(result.definition.name);
      setDescription(result.definition.description ?? "");
      setTerms(result.definition.terms.join("\n"));
      setBaseline(JSON.stringify(result.definition));
      try {
        await put(`/keyword-rules/${result.id}/targets`, {
          target_ids: targetIds,
        });
      } catch (mappingError) {
        setMappingNeedsRetry(true);
        throw new Error(
          `검색 조건은 저장됐지만 분석 대상 연결을 저장하지 못했어요. ${
            mappingError instanceof Error ? mappingError.message : ""
          }`,
        );
      }
      setMappingNeedsRetry(false);
      await ruleTargets.refetch();
      setSaved(true);
      await cache.invalidateQueries();
      if (!rule) router.push(`/keywords/${result.id}?saved=1`);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("저장하지 못했어요."));
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
        title={activeRule ? activeRule.definition.name : "새 검색 조건"}
        description="같은 주제의 키워드를 묶고, 수집 전에 검색 결과를 확인해 보세요."
      />
      {error && <ErrorNotice error={error} />}
      {saved && !dirty && (
        <div className="notice" role="status">
          검색 조건을 저장했어요. 아래에서 미리보기를 확인하거나 수집을 요청할
          수 있어요.
        </div>
      )}
      {activeRule && (
        <div className="context-actions">
          <Link
            href={`/runs?rule_id=${activeRule.id}`}
            className="button secondary"
          >
            이 조건의 수집 이력
          </Link>
          <Link href={`/runs/new?rule=${activeRule.id}`} className="button">
            기간·새 자료 수집
          </Link>
          <span className="hint">
            {dirty ? "저장하지 않은 변경 내용이 있어요" : "저장된 검색 조건"}
          </span>
        </div>
      )}
      <div className="editor-grid">
        <form className="panel" onSubmit={save}>
          <section className="form-section">
            <h2>검색 조건</h2>
            <div className="form-stack">
              <div className="field">
                <label htmlFor="rule-name">조건 이름</label>
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
                  placeholder="어떤 내용을 살펴보는 조건인가요?"
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
              <fieldset className="field">
                <legend>연결할 분석 대상</legend>
                <p className="hint">
                  같은 자료를 여러 분석에서 함께 사용할 수 있어요. 본문은 한
                  번만 수집하고, 이 검색 조건의 발견 이력은 각각 보존돼요.
                </p>
                {targets.error ? (
                  <ErrorNotice
                    error={targets.error}
                    retry={() => targets.refetch()}
                  />
                ) : (
                  <div className="check-list">
                    {targets.data?.map((target) => {
                      const checked = targetIds.includes(target.id);
                      return (
                        <label key={target.id}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) =>
                              setTargetIds((current) =>
                                event.target.checked
                                  ? [...new Set([...current, target.id])]
                                  : current.filter((id) => id !== target.id),
                              )
                            }
                          />
                          {target.name}{" "}
                          <span className="muted">
                            ({targetKindNames[target.kind]})
                          </span>
                        </label>
                      );
                    })}
                    {!targets.data?.length && (
                      <span className="hint">
                        먼저 기사 분석 대상을 등록해 주세요.
                      </span>
                    )}
                  </div>
                )}
                {ruleTargets.error && (
                  <ErrorNotice
                    error={ruleTargets.error}
                    retry={() => ruleTargets.refetch()}
                  />
                )}
                {activeRule && !targetMappingReady && !ruleTargets.error && (
                  <p className="hint">
                    기존 분석 대상 연결을 불러오는 중이에요.
                  </p>
                )}
              </fieldset>
            </div>
          </section>
          <section className="form-section">
            <h2>자동 수집</h2>
            <div className="form-stack">
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                자동 수집 사용
              </label>
              <p className="hint">
                자동 수집을 켜면 이 조건이 자동 수집 대상에 포함돼요. 이전
                자료가 필요하면 기간 수집을 별도로 요청해 주세요.
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
              disabled={pending !== null || !targetMappingReady}
            >
              <FloppyDiskIcon size={18} />
              {pending === "save" ? "저장 중…" : "검색 조건 저장"}
            </button>
          </div>
        </form>
        <KeywordPreview definition={definition} />
      </div>
      {activeRule && (
        <section className="panel section-gap">
          <div className="panel-body">
            <h2>검색 조건 변경 이력</h2>
            <p className="hint section-gap">
              조건을 바꾸기 전 요청은 당시 조건으로 보존돼요.
            </p>
            {versions.error ? (
              <ErrorNotice
                error={versions.error}
                retry={() => versions.refetch()}
              />
            ) : (
              <ul className="history-list">
                {versions.data?.map((version) => (
                  <li key={version.version}>
                    <strong>{version.definition.name}</strong>
                    <span>{version.definition.terms.join(" · ")}</span>
                    <span className="hint">
                      {new Date(version.created_at).toLocaleString("ko-KR", {
                        timeZone: "Asia/Seoul",
                      })}{" "}
                      · 저장 기록 {version.version}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}
    </>
  );
}
