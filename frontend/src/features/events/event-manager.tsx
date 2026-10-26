"use client";

import { type FormEvent, useState } from "react";
import { post, put, remove, useApi } from "@/shared/api/client";
import type { components } from "@/shared/api/schema";
import { Empty, ErrorNotice, Loading, PageHeading } from "@/shared/ui/feedback";
import type { Tag, TagFolder } from "../articles/types";
import { FolderTree } from "../classification/folder-tree";

type EventItem = components["schemas"]["EventInfo"];
type UnfiledSummary = components["schemas"]["UnfiledTagSummary"];

export function EventManager() {
  const query = useApi<EventItem[]>("/events");
  const tags = useApi<Tag[]>("/tags?inclusion=all", false);
  const folders = useApi<TagFolder[]>("/tag-folders?inclusion=all", false);
  const unfiled = useApi<UnfiledSummary>(
    "/tags/unfiled/summary?inclusion=all",
    false,
  );
  const [editing, setEditing] = useState<EventItem | null>(null);
  const [name, setName] = useState("");
  const [occurredAt, setOccurredAt] = useState("");
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [folderIds, setFolderIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const edit = (item: EventItem | null) => {
    setEditing(item);
    setName(item?.name ?? "");
    setOccurredAt(item ? localDateTime(item.occurred_at) : "");
    setTagIds(
      item?.targets
        .filter((target) => target.kind === "tag")
        .map((target) => target.id) ?? [],
    );
    setFolderIds(
      item?.targets
        .filter((target) => target.kind === "folder")
        .map((target) => target.id) ?? [],
    );
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (saving) return;
    const body = {
      name,
      occurred_at: `${occurredAt}:00+09:00`,
      tag_ids: tagIds,
      folder_ids: folderIds,
    };
    try {
      setSaving(true);
      if (editing)
        await put(`/events/${editing.id}`, {
          ...body,
          version: editing.version,
        });
      else await post("/events", body);
      edit(null);
      setError("");
      await query.refetch();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "저장하지 못했어요.");
    } finally {
      setSaving(false);
    }
  };
  return (
    <>
      <PageHeading
        title="이벤트"
        action={
          <button className="button" type="button" onClick={() => edit(null)}>
            이벤트 등록
          </button>
        }
      />
      <section className="panel panel-body">
        <form className="form-stack" onSubmit={submit}>
          <div className="field">
            <label>
              이름
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={200}
                required
              />
            </label>
          </div>
          <div className="field">
            <label>
              기준 시각
              <input
                type="datetime-local"
                value={occurredAt}
                onChange={(event) => setOccurredAt(event.target.value)}
                required
              />
            </label>
          </div>
          <div className="field">
            <strong>연결 대상</strong>
            <FolderTree
              folders={folders.data ?? []}
              tags={tags.data ?? []}
              unfiledCount={unfiled.data?.material_count ?? 0}
              selectedFolderIds={folderIds}
              selectedTagIds={tagIds}
              onSelectFolder={(id, checked) =>
                setFolderIds(
                  checked
                    ? [...folderIds, id]
                    : folderIds.filter((value) => value !== id),
                )
              }
              onSelectTag={(id, checked) =>
                setTagIds(
                  checked
                    ? [...tagIds, id]
                    : tagIds.filter((value) => value !== id),
                )
              }
            />
          </div>
          {tags.error && (
            <ErrorNotice error={tags.error} retry={tags.refetch} />
          )}
          {folders.error && (
            <ErrorNotice error={folders.error} retry={folders.refetch} />
          )}
          {unfiled.error && (
            <ErrorNotice error={unfiled.error} retry={unfiled.refetch} />
          )}
          <div className="button-row">
            <button className="button" type="submit" disabled={saving}>
              {editing ? "수정 저장" : "등록"}
            </button>
            {editing && (
              <button
                className="button quiet"
                type="button"
                onClick={() => edit(null)}
              >
                취소
              </button>
            )}
          </div>
          {error && <span role="alert">{error}</span>}
        </form>
      </section>
      {query.error ? (
        <ErrorNotice error={query.error} retry={query.refetch} />
      ) : query.isLoading ? (
        <Loading />
      ) : !query.data?.length ? (
        <Empty title="등록한 이벤트가 없어요" />
      ) : (
        <section className="panel section-gap">
          <ul className="management-list">
            {query.data.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <span>
                    {new Intl.DateTimeFormat("ko-KR", {
                      timeZone: "Asia/Seoul",
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(item.occurred_at))}{" "}
                  </span>
                  <span>
                    {item.targets.map((target) => target.name).join(", ") ||
                      "연결 대상 없음"}
                  </span>
                </div>
                <div className="button-row">
                  <button
                    className="button quiet"
                    type="button"
                    onClick={() => edit(item)}
                  >
                    수정
                  </button>
                  <button
                    className="button quiet"
                    type="button"
                    onClick={async () => {
                      try {
                        setSaving(true);
                        await remove(
                          `/events/${item.id}?version=${item.version}`,
                        );
                        setError("");
                        await query.refetch();
                      } catch (reason) {
                        setError(
                          reason instanceof Error
                            ? reason.message
                            : "삭제하지 못했어요.",
                        );
                      } finally {
                        setSaving(false);
                      }
                    }}
                    disabled={saving}
                  >
                    삭제
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
function localDateTime(value: string) {
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const part = (type: string) =>
    parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}
