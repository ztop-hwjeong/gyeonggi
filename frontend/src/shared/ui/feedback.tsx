"use client";

import { ArrowClockwiseIcon, WarningCircleIcon } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { stateNames } from "../lib/format";

export function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

export function ErrorNotice({
  error,
  retry,
}: {
  error: Error;
  retry?: () => void;
}) {
  return (
    <div className="notice danger" role="alert">
      <WarningCircleIcon size={20} />
      <span>{error.message}</span>
      {retry && (
        <button type="button" className="button quiet" onClick={retry}>
          다시 시도
        </button>
      )}
    </div>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function Loading() {
  return (
    <div className="loading" role="status">
      <ArrowClockwiseIcon className="spin" size={20} /> 불러오는 중이에요
    </div>
  );
}

export function State({ value }: { value: string }) {
  return (
    <span
      className={`state ${["failed", "partial"].includes(value) ? value : ""}`}
    >
      <span className="state-dot" aria-hidden="true" />
      {stateNames[value] ?? value}
    </span>
  );
}

export function Pager({
  total,
  offset,
  size,
  onChange,
}: {
  total: number;
  offset: number;
  size: number;
  onChange: (offset: number) => void;
}) {
  return (
    <div className="pager">
      <span>전체 {total.toLocaleString("ko-KR")}건</span>
      <div>
        <button
          type="button"
          className="button secondary"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - size))}
        >
          이전
        </button>
        <span>
          {Math.floor(offset / size) + 1} /{" "}
          {Math.max(1, Math.ceil(total / size))}
        </span>
        <button
          type="button"
          className="button secondary"
          disabled={offset + size >= total}
          onClick={() => onChange(offset + size)}
        >
          다음
        </button>
      </div>
    </div>
  );
}
