"use client";

import { ArrowLeftIcon } from "@phosphor-icons/react";
import { type ReactNode, useEffect, useRef } from "react";

export function ReadingRow({
  id,
  title,
  meta,
  onOpen,
}: {
  id: string;
  title: string;
  meta: string;
  onOpen: () => void;
}) {
  return (
    <li>
      <button id={id} type="button" className="reading-row" onClick={onOpen}>
        <span className="reading-row-title">{title}</span>
        <span className="reading-meta">{meta}</span>
      </button>
    </li>
  );
}

export function ReadingView({
  title,
  meta,
  onBack,
  children,
}: {
  title: string;
  meta: string;
  onBack: () => void;
  children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <article className="reading-view">
      <button
        type="button"
        className="button quiet reading-back"
        onClick={onBack}
      >
        <ArrowLeftIcon size={16} />
        목록으로
      </button>
      <h2 tabIndex={-1} ref={heading}>
        {title}
      </h2>
      <p className="reading-meta">{meta}</p>
      <div className="reading-text">{children}</div>
    </article>
  );
}
