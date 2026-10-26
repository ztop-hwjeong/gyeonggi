"use client";

import {
  CaretDownIcon,
  CaretRightIcon,
  DotsThreeIcon,
  FolderIcon,
  TagIcon,
} from "@phosphor-icons/react";
import { type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Tag, TagFolder } from "../articles/types";

export type TagEntry = { tagId: string; folderId: string | null };
export type DragEntry =
  | { kind: "folder"; id: string }
  | { kind: "tag"; id: string; sourceFolderId: string | null };
type TreeNode = { info: TagFolder; children: TreeNode[]; tags: Tag[] };
type MenuTarget =
  | { kind: "folder"; folder: TagFolder }
  | { kind: "tag"; tag: Tag; folderId: string | null }
  | { kind: "root" };
type Menu = MenuTarget & { x: number; y: number };

export function canMoveFolder(
  folders: TagFolder[],
  sourceId: string,
  targetId: string | null,
) {
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  const source = byId.get(sourceId);
  if (!source || source.parent_id === targetId) return false;
  const seen = new Set<string>();
  for (let id = targetId; id !== null; id = byId.get(id)?.parent_id ?? null) {
    if (id === sourceId || seen.has(id)) return false;
    seen.add(id);
  }
  return true;
}

export function FolderTree({
  folders,
  tags,
  unfiledCount,
  selectedFolderId,
  selectedTagId,
  selectedFolderIds,
  selectedTagIds,
  selectedTagEntries,
  onFolderOpen,
  onTagOpen,
  onSelectFolder,
  onSelectTag,
  onSelectTagEntry,
  onFolderAction,
  onCreateRoot,
  onTagAction,
  onDrop,
  folderCounts = true,
  busy = false,
}: {
  folders: TagFolder[];
  tags: Tag[];
  unfiledCount?: number;
  selectedFolderId?: string | null;
  selectedTagId?: string;
  selectedFolderIds?: string[];
  selectedTagIds?: string[];
  selectedTagEntries?: TagEntry[];
  onFolderOpen?: (id: string | null) => void;
  onTagOpen?: (id: string) => void;
  onSelectFolder?: (id: string, checked: boolean) => void;
  onSelectTag?: (id: string, checked: boolean) => void;
  onSelectTagEntry?: (entry: TagEntry, checked: boolean) => void;
  onFolderAction?: (
    folder: TagFolder,
    action: "create" | "rename" | "delete",
  ) => void;
  onCreateRoot?: () => void;
  onTagAction?: (tag: Tag, sourceFolderId: string | null) => void;
  onDrop?: (entry: DragEntry, targetId: string | null) => Promise<void>;
  folderCounts?: boolean;
  busy?: boolean;
}) {
  const tree = useMemo(() => makeTree(folders, tags), [folders, tags]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [menu, setMenu] = useState<Menu | null>(null);
  const menuOpener = useRef<HTMLElement | null>(null);
  const [dragging, setDragging] = useState<DragEntry | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  useEffect(() => {
    if (!dragging) return;
    const cancel = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDragging(null);
        setDropTarget(null);
      }
    };
    window.addEventListener("keydown", cancel);
    const timer =
      dropTarget && dropTarget !== "root"
        ? window.setTimeout(() => {
            setExpanded((value) => new Set(value).add(dropTarget));
          }, 500)
        : undefined;
    return () => {
      window.removeEventListener("keydown", cancel);
      window.clearTimeout(timer);
    };
  }, [dragging, dropTarget]);
  useEffect(() => {
    if (!menu) return;
    const close = (event: PointerEvent) => {
      if (
        !(event.target instanceof Element) ||
        !event.target.closest(".tree-context-menu,.tree-more")
      )
        setMenu(null);
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenu(null);
        menuOpener.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", handleEscape);
    const frame = requestAnimationFrame(() =>
      document
        .querySelector<HTMLButtonElement>(".tree-context-menu button")
        ?.focus(),
    );
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [menu]);
  const openMenu = (value: MenuTarget, x: number, y: number) => {
    const height = value.kind === "folder" ? 128 : 44;
    setMenu({
      ...value,
      x: Math.max(8, Math.min(x, window.innerWidth - 180)),
      y: Math.max(8, Math.min(y, window.innerHeight - height - 8)),
    });
  };
  const toggle = (id: string) =>
    setExpanded((value) => {
      const next = new Set(value);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const canDrop = (targetId: string | null) =>
    !!dragging &&
    !busy &&
    (dragging.kind === "folder"
      ? canMoveFolder(folders, dragging.id, targetId)
      : dragging.sourceFolderId !== targetId);
  const drop = (event: DragEvent, targetId: string | null) => {
    if (!canDrop(targetId) || !dragging) return;
    event.preventDefault();
    void onDrop?.(dragging, targetId);
    setDragging(null);
    setDropTarget(null);
  };
  const start = (event: DragEvent, entry: DragEntry) => {
    if (busy || !onDrop) return;
    event.stopPropagation();
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", entry.id);
    setDragging(entry);
  };
  const row = (
    folder: TagFolder,
    depth: number,
    tagsInFolder: Tag[],
    children: TreeNode[],
  ) => {
    const isUnfiled = folder.id === "unfiled";
    const folderId = isUnfiled ? null : folder.id;
    const open = expanded.has(folder.id);
    const active =
      selectedFolderId === folder.id ||
      (isUnfiled && selectedFolderId === "unfiled");
    return (
      <div key={folder.id} className="tree-branch">
        {/* biome-ignore lint/a11y/noStaticElementInteractions: 이동의 키보드 조작은 아이콘·폴더 이름 버튼 제공 */}
        <div
          className={`tree-folder ${active ? "active" : ""} ${dropTarget === folder.id ? "drop-target" : ""}`}
          draggable={!!onDrop && !isUnfiled && !busy}
          onDragStart={(event) => {
            if (
              event.target instanceof Element &&
              event.target.closest(".tree-chevron,.tree-more,input")
            ) {
              event.preventDefault();
              return;
            }
            start(event, { kind: "folder", id: folder.id });
          }}
          onDragEnd={() => {
            setDragging(null);
            setDropTarget(null);
          }}
          style={{ paddingLeft: `${depth * 18}px` }}
          onContextMenu={(event) => {
            if (!onFolderAction || isUnfiled) return;
            event.preventDefault();
            menuOpener.current =
              event.currentTarget.querySelector(".tree-more");
            openMenu({ kind: "folder", folder }, event.clientX, event.clientY);
          }}
          onDragOver={(event) => {
            if (isUnfiled && dragging?.kind === "folder") return;
            if (!canDrop(folderId)) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            setDropTarget(folder.id);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node))
              setDropTarget(null);
          }}
          onDrop={(event) => {
            if (isUnfiled && dragging?.kind === "folder") return;
            drop(event, folderId);
          }}
        >
          <button
            className="tree-chevron"
            type="button"
            onClick={() => toggle(folder.id)}
            aria-label={`${folder.name} ${open ? "접기" : "펼치기"}`}
            aria-expanded={open}
          >
            {open ? <CaretDownIcon size={15} /> : <CaretRightIcon size={15} />}
          </button>
          {onSelectFolder && !isUnfiled && (
            <input
              type="checkbox"
              aria-label={`${folder.name} 선택`}
              checked={selectedFolderIds?.includes(folder.id) ?? false}
              onChange={(event) =>
                onSelectFolder(folder.id, event.target.checked)
              }
            />
          )}
          {onDrop && !isUnfiled ? (
            <button
              className="tree-drag"
              type="button"
              draggable
              disabled={busy}
              aria-label={`${folder.name} 끌어서 이동`}
              onDragStart={(event) =>
                start(event, { kind: "folder", id: folder.id })
              }
              onKeyDown={(event) => {
                if (event.key === " " || event.key === "Enter") {
                  event.preventDefault();
                  setDragging({ kind: "folder", id: folder.id });
                }
              }}
              onDragEnd={() => {
                setDragging(null);
                setDropTarget(null);
              }}
            >
              <FolderIcon size={20} />
            </button>
          ) : (
            <span className="tree-icon folder-icon">
              <FolderIcon size={20} />
            </span>
          )}
          <button
            className="tree-name"
            type="button"
            draggable={!!onDrop && !isUnfiled && !busy}
            onDragStart={(event) =>
              start(event, { kind: "folder", id: folder.id })
            }
            onDragEnd={() => {
              setDragging(null);
              setDropTarget(null);
            }}
            aria-label={folder.name}
            aria-current={active ? "true" : undefined}
            onClick={() =>
              onFolderOpen ? onFolderOpen(folderId) : toggle(folder.id)
            }
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setDragging(null);
                setDropTarget(null);
              } else if (
                dragging &&
                (event.key === " " || event.key === "Enter") &&
                canDrop(folderId) &&
                !(isUnfiled && dragging.kind === "folder")
              ) {
                event.preventDefault();
                void onDrop?.(dragging, folderId);
                setDragging(null);
                setDropTarget(null);
              }
            }}
          >
            <span className="tree-label">
              <strong>{folder.name}</strong>
              {folderCounts && (
                <small>
                  자료 {isUnfiled ? (unfiledCount ?? 0) : folder.material_count}
                </small>
              )}
            </span>
          </button>
          {onFolderAction && !isUnfiled && (
            <button
              type="button"
              className="tree-more"
              aria-label={`${folder.name} 메뉴`}
              aria-expanded={
                menu?.kind === "folder" && menu.folder.id === folder.id
              }
              onClick={(event) => {
                menuOpener.current = event.currentTarget;
                if (menu?.kind === "folder" && menu.folder.id === folder.id)
                  setMenu(null);
                else {
                  const rect = event.currentTarget.getBoundingClientRect();
                  openMenu({ kind: "folder", folder }, rect.right, rect.bottom);
                }
              }}
            >
              <DotsThreeIcon size={18} />
            </button>
          )}
        </div>
        {open &&
          children.map((child) =>
            row(child.info, depth + 1, child.tags, child.children),
          )}
        {open &&
          tagsInFolder.map((tag) => {
            const entry = { tagId: tag.id, folderId };
            const checked = onSelectTag
              ? (selectedTagIds?.includes(tag.id) ?? false)
              : (selectedTagEntries?.some(
                  (item) => item.tagId === tag.id && item.folderId === folderId,
                ) ?? false);
            return (
              // biome-ignore lint/a11y/noStaticElementInteractions: 우클릭 메뉴의 키보드 대체는 행 버튼 제공
              <div
                key={JSON.stringify([folderId, tag.id])}
                className={`tree-tag ${selectedTagId === tag.id ? "active" : ""}`}
                style={{ paddingLeft: `${(depth + 1) * 18 + 22}px` }}
                onContextMenu={(event) => {
                  if (!onTagAction) return;
                  event.preventDefault();
                  menuOpener.current =
                    event.currentTarget.querySelector(".tree-more");
                  openMenu(
                    { kind: "tag", tag, folderId },
                    event.clientX,
                    event.clientY,
                  );
                }}
              >
                <input
                  type="checkbox"
                  aria-label={`${folder.name} ${tag.name} 선택`}
                  checked={checked}
                  onChange={(event) =>
                    onSelectTag
                      ? onSelectTag(tag.id, event.target.checked)
                      : onSelectTagEntry?.(entry, event.target.checked)
                  }
                />
                {onDrop ? (
                  <button
                    className="tree-drag tag-icon"
                    type="button"
                    draggable
                    disabled={busy}
                    aria-label={`${tag.name} 끌어서 이동`}
                    onDragStart={(event) =>
                      start(event, {
                        kind: "tag",
                        id: tag.id,
                        sourceFolderId: folderId,
                      })
                    }
                    onDragEnd={() => {
                      setDragging(null);
                      setDropTarget(null);
                    }}
                  >
                    <TagIcon size={18} />
                  </button>
                ) : (
                  <span className="tree-icon tag-icon">
                    <TagIcon size={18} />
                  </span>
                )}
                <button
                  className="tree-name"
                  type="button"
                  aria-label={tag.name}
                  aria-current={selectedTagId === tag.id ? "true" : undefined}
                  onClick={() =>
                    onTagOpen
                      ? onTagOpen(tag.id)
                      : onSelectTag?.(tag.id, !checked)
                  }
                >
                  <span className="tree-label">
                    <strong>{tag.name}</strong>
                    {folderCounts && <small>자료 {tag.material_count}</small>}
                  </span>
                </button>
                {onTagAction && (
                  <button
                    type="button"
                    className="tree-more"
                    aria-label={`${tag.name} 이동`}
                    onClick={(event) => {
                      menuOpener.current = event.currentTarget;
                      const rect = event.currentTarget.getBoundingClientRect();
                      openMenu(
                        { kind: "tag", tag, folderId },
                        rect.right,
                        rect.bottom,
                      );
                    }}
                  >
                    <DotsThreeIcon size={18} />
                  </button>
                )}
              </div>
            );
          })}
      </div>
    );
  };
  const unfiledFolder = {
    id: "unfiled",
    name: "미분류 태그",
    parent_id: null,
    version: 0,
    tag_count: tree.unfiled.length,
    material_count: unfiledCount ?? 0,
    created_at: "",
    updated_at: "",
  };
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: 빈 영역 우클릭의 키보드 대체는 폴더 추가 버튼 제공
    <div
      className="folder-tree"
      onContextMenu={(event) => {
        if (
          !onCreateRoot ||
          !(event.target instanceof Element) ||
          event.target.closest(".tree-folder,.tree-tag")
        )
          return;
        event.preventDefault();
        menuOpener.current = document.querySelector(".tree-toolbar button");
        openMenu({ kind: "root" }, event.clientX, event.clientY);
      }}
    >
      {onDrop && dragging?.kind === "folder" && (
        <button
          type="button"
          className={`tree-root-drop ${dropTarget === "root" ? "drop-target" : ""}`}
          onClick={() => {
            if (dragging && canDrop(null)) void onDrop(dragging, null);
            setDragging(null);
            setDropTarget(null);
          }}
          onDragOver={(event) => {
            if (canDrop(null)) {
              event.preventDefault();
              setDropTarget("root");
            }
          }}
          onDrop={(event) => drop(event, null)}
        >
          최상위로 이동
        </button>
      )}
      {row(unfiledFolder, 0, tree.unfiled, [])}
      {tree.roots.map((node) => row(node.info, 0, node.tags, node.children))}
      {menu && (
        <fieldset
          className="tree-context-menu"
          aria-label={
            menu.kind === "folder"
              ? "폴더 메뉴"
              : menu.kind === "tag"
                ? "태그 메뉴"
                : "자료 분류 메뉴"
          }
          style={{ left: menu.x, top: menu.y }}
        >
          {menu.kind === "folder" &&
            onFolderAction &&
            (
              [
                ["create", "하위 폴더 만들기"],
                ["rename", "이름 변경"],
                ["delete", "폴더 삭제"],
              ] as const
            ).map(([action, label]) => (
              <button
                key={action}
                type="button"
                onClick={() => {
                  setMenu(null);
                  onFolderAction(menu.folder, action);
                }}
              >
                {label}
              </button>
            ))}
          {menu.kind === "tag" && onTagAction && (
            <button
              type="button"
              onClick={() => {
                setMenu(null);
                onTagAction(menu.tag, menu.folderId);
              }}
            >
              태그 이동
            </button>
          )}
          {menu.kind === "root" && onCreateRoot && (
            <button
              type="button"
              onClick={() => {
                setMenu(null);
                onCreateRoot();
              }}
            >
              새 폴더
            </button>
          )}
        </fieldset>
      )}
    </div>
  );
}

function makeTree(folders: TagFolder[], tags: Tag[]) {
  const nodes = new Map<string, TreeNode>(
    folders.map((info) => [info.id, { info, children: [], tags: [] }]),
  );
  const roots: TreeNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.info.parent_id
      ? nodes.get(node.info.parent_id)
      : undefined;
    parent ? parent.children.push(node) : roots.push(node);
  }
  for (const tag of tags)
    for (const folderId of tag.folder_ids) nodes.get(folderId)?.tags.push(tag);
  return { roots, unfiled: tags.filter((tag) => !tag.folder_ids.length) };
}
