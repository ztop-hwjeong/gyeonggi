"use client";

import { type KeyboardEvent, useState } from "react";
import { FeedbackExample, InputExample, ReadingExample } from "./examples";
import "./catalog.css";

const views = [
  { id: "reading", label: "자료 읽기" },
  { id: "input", label: "키워드 입력" },
  { id: "feedback", label: "알림" },
  { id: "foundations", label: "색과 글자" },
] as const;
type View = (typeof views)[number]["id"];

export function DesignCatalog() {
  const [view, setView] = useState<View>("reading");
  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % views.length
        : event.key === "ArrowLeft"
          ? (index + views.length - 1) % views.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? views.length - 1
              : null;
    if (next === null) return;
    event.preventDefault();
    setView(views[next].id);
    document.getElementById(`design-tab-${views[next].id}`)?.focus();
  }
  return (
    <main id="main" className="design-catalog">
      <header className="catalog-heading">
        <h1>화면 디자인 기준</h1>
        <p>예시 데이터로 구성한 검토 화면</p>
      </header>
      <div className="catalog-tabs" role="tablist" aria-label="디자인 예시">
        {views.map((item, index) => (
          <button
            type="button"
            role="tab"
            key={item.id}
            id={`design-tab-${item.id}`}
            aria-selected={view === item.id}
            aria-controls={`design-panel-${item.id}`}
            tabIndex={view === item.id ? 0 : -1}
            onKeyDown={(event) => move(event, index)}
            onClick={() => setView(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {views.map((item) => (
        <section
          key={item.id}
          role="tabpanel"
          id={`design-panel-${item.id}`}
          aria-labelledby={`design-tab-${item.id}`}
          hidden={view !== item.id}
          className="catalog-panel"
        >
          {view === item.id &&
            (view === "reading" ? (
              <ReadingExample />
            ) : view === "input" ? (
              <InputExample />
            ) : view === "feedback" ? (
              <FeedbackExample />
            ) : (
              <FoundationsExample />
            ))}
        </section>
      ))}
    </main>
  );
}

function FoundationsExample() {
  return (
    <section className="catalog-foundations">
      <h2>색과 글자</h2>
      <div className="catalog-swatches">
        {[
          { label: "주요 동작", color: "var(--color-action-primary)" },
          { label: "기본 글자", color: "var(--color-text-primary)" },
          { label: "화면 바탕", color: "var(--color-surface-canvas)" },
          { label: "내용 바탕", color: "var(--color-surface-default)" },
        ].map((item) => (
          <div key={item.label}>
            <span
              className="catalog-swatch"
              style={{ background: item.color }}
            />
            <span>{item.label}</span>
          </div>
        ))}
      </div>
      <div className="catalog-type-examples">
        <p className="catalog-type-title">화면의 제목</p>
        <p className="catalog-type-section">내용의 제목</p>
        <p>자료를 편안하게 읽을 수 있는 기본 글자예요.</p>
        <p className="catalog-meta-example">발행처 · 날짜처럼 짧은 정보예요.</p>
      </div>
      <div className="catalog-button-examples">
        <button className="button" type="button">
          주요 동작
        </button>
        <button className="button secondary" type="button">
          보조 동작
        </button>
        <button className="button" type="button" disabled>
          사용할 수 없음
        </button>
      </div>
    </section>
  );
}
