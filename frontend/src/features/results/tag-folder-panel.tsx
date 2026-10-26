"use client";

import { PlusIcon } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { post, put, remove, useApi } from "@/shared/api/client";
import { ErrorNotice, Loading } from "@/shared/ui/feedback";
import type {
  MaterialKind,
  Tag,
  TagFolder,
  UnfiledTagSummary,
} from "../articles/types";

import {
  canMoveFolder,
  type DragEntry,
  FolderTree,
  type TagEntry,
} from "../classification/folder-tree";

type Selection = TagEntry;
type Editor =
  | { action: "create"; parentId: string | null }
  | { action: "rename" | "delete"; folder: TagFolder }
  | { action: "tagMove"; tag: Tag; sourceFolderId: string | null };

function isInFolderTree(
  folders: TagFolder[],
  rootId: string,
  folderId: string,
) {
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  const seen = new Set<string>();
  for (
    let id: string | null = folderId;
    id !== null;
    id = byId.get(id)?.parent_id ?? null
  ) {
    if (id === rootId) return true;
    if (seen.has(id)) break;
    seen.add(id);
  }
  return false;
}

export function TagFolderPanel({
  folderId,
  tagId,
  unfiled,
  kind,
  onChange,
}: {
  folderId: string;
  tagId: string;
  unfiled: boolean;
  kind: "all" | MaterialKind;
  onChange: (values: Record<string, string | null>) => void;
}) {
  const kindQuery = kind === "all" ? "" : `&kind=${kind}`;
  const folders = useApi<TagFolder[]>(
    `/tag-folders?inclusion=all${kindQuery}`,
    false,
  );
  const tags = useApi<Tag[]>(`/tags?inclusion=all${kindQuery}`, false);
  const unfiledSummary = useApi<UnfiledTagSummary>(
    `/tags/unfiled/summary?inclusion=all${kindQuery}`,
    false,
  );
  const [selected, setSelected] = useState<Selection[]>([]);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [name, setName] = useState("");
  const [destination, setDestination] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const queryClient = useQueryClient();
  const loadError = folders.error ?? tags.error;
  const refresh = async () => {
    await Promise.all([
      folders.refetch(),
      tags.refetch(),
      unfiledSummary.refetch(),
    ]);
    await queryClient.invalidateQueries({
      predicate: ({ queryKey }) =>
        typeof queryKey[0] === "string" &&
        (queryKey[0].startsWith("/tag-folders") ||
          queryKey[0].startsWith("/tags") ||
          queryKey[0].startsWith("/materials") ||
          queryKey[0].startsWith("/articles")),
    });
    setSelected([]);
  };
  const select = (entry: Selection, checked: boolean) =>
    setSelected((value) =>
      checked
        ? [...value, entry]
        : value.filter(
            (item) =>
              item.tagId !== entry.tagId || item.folderId !== entry.folderId,
          ),
    );
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!editor || (!name.trim() && editor.action !== "tagMove")) return;
    try {
      setBusy(true);
      if (editor.action === "create") {
        await post("/tag-folders", {
          name: name.trim(),
          parent_id: editor.parentId,
        });
      } else if (editor.action === "rename") {
        await put(`/tag-folders/${editor.folder.id}`, {
          name: name.trim(),
          parent_id: editor.folder.parent_id,
          version: editor.folder.version,
        });
      } else if (editor.action === "tagMove") {
        await post("/tag-folders/tag-moves", {
          tag_id: editor.tag.id,
          source_folder_id: editor.sourceFolderId,
          target_folder_id: destination,
        });
      }
      setEditor(null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "저장하지 못했어요.");
    } finally {
      setBusy(false);
    }
  };
  const runDrop = async (entry: DragEntry, target: string | null) => {
    try {
      setBusy(true);
      setError("");
      if (entry.kind === "folder") {
        const source = folders.data?.find((item) => item.id === entry.id);
        if (!source || !canMoveFolder(folders.data ?? [], entry.id, target))
          return;
        await put(`/tag-folders/${entry.id}`, {
          name: source.name,
          parent_id: target,
          version: source.version,
        });
      } else {
        if (entry.sourceFolderId === target) return;
        await post("/tag-folders/tag-moves", {
          tag_id: entry.id,
          source_folder_id: entry.sourceFolderId,
          target_folder_id: target,
        });
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "이동하지 못했어요.");
    } finally {
      setBusy(false);
    }
  };
  const openEditor = (value: Editor) => {
    setError("");
    setEditor(value);
    if (value.action === "create") {
      setName("");
      setDestination(value.parentId);
    } else if (value.action === "tagMove") {
      setDestination(value.sourceFolderId);
    } else {
      setName(value.folder.name);
      setDestination(value.folder.parent_id);
    }
  };
  const deleteFolder = async () => {
    if (editor?.action !== "delete") return;
    try {
      setBusy(true);
      await remove(
        `/tag-folders/${editor.folder.id}?version=${editor.folder.version}`,
      );
      if (
        folderId &&
        isInFolderTree(folders.data ?? [], editor.folder.id, folderId)
      )
        changeFolder(null);
      setEditor(null);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "삭제하지 못했어요.");
    } finally {
      setBusy(false);
    }
  };
  const attach = async () => {
    if (!folderId || !selected.length) return;
    await post(`/tag-folders/${folderId}/tags`, {
      tag_ids: [...new Set(selected.map((item) => item.tagId))],
    });
    await refresh();
    if (unfiled && tagId && selected.some((item) => item.tagId === tagId)) {
      onChange({ folder_id: folderId, tag_id: null, unfiled: null });
    }
  };
  const detach = async () => {
    await Promise.all(
      selected
        .filter((item) => item.folderId)
        .map((item) =>
          remove(`/tag-folders/${item.folderId}/tags/${item.tagId}`),
        ),
    );
    await refresh();
  };
  const changeFolder = (id: string | null, isUnfiled = false) =>
    onChange({
      folder_id: id,
      tag_id: null,
      unfiled: isUnfiled ? "true" : null,
    });
  const deleteChildCount =
    editor?.action === "delete"
      ? (folders.data ?? []).filter(
          (item) =>
            item.id !== editor.folder.id &&
            isInFolderTree(folders.data ?? [], editor.folder.id, item.id),
        ).length
      : 0;
  return (
    <aside className="tag-folder-panel" aria-label="자료 분류">
      <div className="tree-toolbar">
        <strong>자료 분류</strong>
        <button
          className="button quiet"
          type="button"
          aria-label="폴더 추가"
          onClick={() =>
            openEditor({ action: "create", parentId: folderId || null })
          }
        >
          <PlusIcon size={16} />
        </button>
      </div>
      {loadError ? (
        <ErrorNotice error={loadError} retry={refresh} />
      ) : folders.isLoading || tags.isLoading ? (
        <Loading />
      ) : (
        <FolderTree
          folders={folders.data ?? []}
          tags={tags.data ?? []}
          unfiledCount={unfiledSummary.data?.material_count}
          selectedFolderId={unfiled ? "unfiled" : folderId}
          selectedTagId={tagId}
          selectedTagEntries={selected}
          onFolderOpen={(id) => changeFolder(id, id === null)}
          onTagOpen={(id) =>
            onChange({ folder_id: null, tag_id: id, unfiled: null })
          }
          onSelectTagEntry={select}
          onFolderAction={(folder, action) =>
            openEditor(
              action === "create"
                ? { action, parentId: folder.id }
                : { action, folder },
            )
          }
          onCreateRoot={() => openEditor({ action: "create", parentId: null })}
          onTagAction={(tag, sourceFolderId) =>
            openEditor({ action: "tagMove", tag, sourceFolderId })
          }
          onDrop={runDrop}
          busy={busy}
        />
      )}
      {editor && (
        <dialog open className="folder-dialog">
          {editor.action === "delete" ? (
            <div className="folder-editor">
              <strong>
                {editor.folder.name} 폴더
                {deleteChildCount
                  ? `와 하위 폴더 ${deleteChildCount}개를`
                  : "를"}{" "}
                삭제할까요?
              </strong>
              <p>
                태그와 자료는 남습니다. 다른 폴더에 속하지 않은 태그는 미분류로
                이동합니다.
              </p>
              <div className="folder-editor-actions">
                <button
                  className="button"
                  type="button"
                  disabled={busy}
                  onClick={deleteFolder}
                >
                  삭제
                </button>
                <button
                  className="button quiet"
                  type="button"
                  onClick={() => setEditor(null)}
                >
                  취소
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={save}>
              <strong>
                {editor.action === "create"
                  ? "폴더 추가"
                  : editor.action === "rename"
                    ? "이름 변경"
                    : "태그 이동"}
              </strong>
              {(editor.action === "create" || editor.action === "rename") && (
                <label>
                  폴더 이름
                  <input
                    autoFocus
                    value={name}
                    maxLength={120}
                    onChange={(event) => setName(event.target.value)}
                    required
                  />
                </label>
              )}
              {editor.action === "tagMove" && (
                <label>
                  이동할 폴더
                  <select
                    value={destination ?? ""}
                    onChange={(event) =>
                      setDestination(event.target.value || null)
                    }
                  >
                    <option value="">미분류</option>
                    {(folders.data ?? [])
                      .filter((item) => item.id !== editor.sourceFolderId)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              <div className="folder-editor-actions">
                <button
                  className="button"
                  type="submit"
                  disabled={
                    busy ||
                    (editor.action === "tagMove" &&
                      destination === editor.sourceFolderId)
                  }
                >
                  저장
                </button>
                <button
                  className="button quiet"
                  type="button"
                  onClick={() => setEditor(null)}
                >
                  취소
                </button>
              </div>
            </form>
          )}
        </dialog>
      )}
      {selected.length > 0 && (
        <div className="tree-actions">
          {folderId && (
            <button className="button quiet" type="button" onClick={attach}>
              선택 태그 편입
            </button>
          )}
          <button className="button quiet" type="button" onClick={detach}>
            선택 태그 해제
          </button>
        </div>
      )}
      {error && <span role="alert">{error}</span>}
    </aside>
  );
}
