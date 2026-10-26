"use client";

import { useRef, useState } from "react";
import { Empty, ErrorNotice, Loading } from "@/shared/ui/feedback";
import { ReadingRow, ReadingView } from "@/shared/ui/reading";

const articles = [
  {
    id: "support",
    title: "학교 현장의 교권 보호 지원 방안",
    publisher: "교육 소식",
    date: "10월 26일",
    channel: "news",
    text: "학교 현장의 의견을 바탕으로 교권 보호 지원 방안을 살펴봅니다. 교사가 교육 활동에 집중할 수 있도록 필요한 지원을 정리했습니다.",
  },
  {
    id: "consultation",
    title: "교육 활동 중 어려움이 생겼을 때 상담받는 방법",
    publisher: "학교 이야기",
    date: "10월 25일",
    channel: "blog",
    text: "교육 활동 중 생기는 어려움에 대해 도움을 구하는 방법을 알아봅니다. 상황을 정리하고 상담을 신청하는 과정을 소개합니다.",
  },
  {
    id: "field",
    title: "학교와 교사가 함께 만드는 안전한 교육 환경",
    publisher: "교육 소식",
    date: "10월 24일",
    channel: "news",
    text: "학교 구성원이 함께 안전한 교육 환경을 만드는 사례를 살펴봅니다. 서로의 경험을 나누고 일상에서 실천할 수 있는 방법을 소개합니다.",
  },
];

export function ReadingExample() {
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState("");
  const [appliedChannel, setAppliedChannel] = useState("");
  const [selected, setSelected] = useState<string>();
  const article = articles.find((item) => item.id === selected);
  const items = articles.filter(
    (item) =>
      (!appliedChannel || item.channel === appliedChannel) &&
      item.title.includes(search),
  );
  if (article)
    return (
      <ReadingView
        title={article.title}
        meta={`${article.publisher} · ${article.date}`}
        onBack={() => {
          setSelected(undefined);
          requestAnimationFrame(() =>
            document.getElementById(`reading-${article.id}`)?.focus(),
          );
        }}
      >
        <p>{article.text}</p>
        <p>
          관련 내용을 학교 구성원과 공유하고, 현장에서 필요한 지원을 확인할 수
          있도록 안내했습니다.
        </p>
      </ReadingView>
    );
  return (
    <section className="catalog-reading">
      <header className="catalog-section-heading">
        <h2>교권 보호</h2>
        <span>{items.length}건</span>
      </header>
      <form
        className="catalog-search"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(draft.trim());
          setAppliedChannel(channel);
        }}
      >
        <div className="catalog-search-line">
          <label className="sr-only" htmlFor="catalog-search">
            자료 검색
          </label>
          <input
            id="catalog-search"
            value={draft}
            placeholder="자료 검색"
            onChange={(event) => setDraft(event.target.value)}
          />
          <button className="button secondary" type="submit">
            검색
          </button>
        </div>
        <div className="field catalog-channel">
          <label htmlFor="catalog-channel">찾을 곳</label>
          <select
            id="catalog-channel"
            value={channel}
            onChange={(event) => setChannel(event.target.value)}
          >
            <option value="">전체</option>
            <option value="news">뉴스</option>
            <option value="blog">블로그</option>
          </select>
        </div>
      </form>
      {!items.length ? (
        <Empty title="찾는 자료가 없어요">
          <button
            type="button"
            className="button quiet"
            onClick={() => {
              setDraft("");
              setSearch("");
              setChannel("");
              setAppliedChannel("");
            }}
          >
            검색 조건 지우기
          </button>
        </Empty>
      ) : (
        <ul className="reading-list">
          {items.map((item) => (
            <ReadingRow
              key={item.id}
              id={`reading-${item.id}`}
              title={item.title}
              meta={`${item.publisher} · ${item.date}`}
              onOpen={() => {
                setSelected(item.id);
              }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

export function InputExample() {
  const [name, setName] = useState("");
  const [terms, setTerms] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const termsInput = useRef<HTMLTextAreaElement>(null);
  return (
    <section className="catalog-form">
      <h2>키워드 추가</h2>
      <form
        noValidate
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          setSaved(false);
          if (!name.trim()) {
            setError("name");
            nameInput.current?.focus();
            return;
          }
          if (!terms.trim()) {
            setError("terms");
            termsInput.current?.focus();
            return;
          }
          setError("");
          setSaved(true);
        }}
      >
        <div className="field">
          <label htmlFor="catalog-name">키워드 이름</label>
          <input
            ref={nameInput}
            id="catalog-name"
            value={name}
            placeholder="예: 교권 보호"
            onChange={(event) => {
              setName(event.target.value);
              setSaved(false);
              if (error === "name") setError("");
            }}
            aria-invalid={error === "name"}
            aria-describedby={
              error === "name" ? "catalog-name-error" : undefined
            }
            required
            maxLength={100}
          />
          {error === "name" && (
            <p id="catalog-name-error" className="field-error" role="alert">
              키워드 이름을 적어 주세요.
            </p>
          )}
        </div>
        <div className="field">
          <label htmlFor="catalog-terms">검색어</label>
          <textarea
            ref={termsInput}
            id="catalog-terms"
            value={terms}
            placeholder="교권보호, 교권 보호"
            onChange={(event) => {
              setTerms(event.target.value);
              setSaved(false);
              if (error === "terms") setError("");
            }}
            aria-invalid={error === "terms"}
            aria-describedby={
              error === "terms" ? "catalog-terms-error" : undefined
            }
            required
          />
          {error === "terms" && (
            <p id="catalog-terms-error" className="field-error" role="alert">
              검색할 말을 적어 주세요.
            </p>
          )}
        </div>
        <label className="check-label">
          <input type="checkbox" />
          자동으로 새 자료 모으기
        </label>
        <div className="catalog-form-end">
          {saved && <p role="status">저장됐어요. 예시 화면에만 적용돼요.</p>}
          <button className="button" type="submit">
            저장
          </button>
        </div>
      </form>
    </section>
  );
}

export function FeedbackExample() {
  const [state, setState] = useState("empty");
  return (
    <section className="catalog-feedback">
      <div className="field">
        <label htmlFor="catalog-state">확인할 상태</label>
        <select
          id="catalog-state"
          value={state}
          onChange={(event) => setState(event.target.value)}
        >
          <option value="empty">아직 자료가 없을 때</option>
          <option value="error">자료를 불러오지 못했을 때</option>
          <option value="loading">불러오는 중</option>
          <option value="done">저장이 끝났을 때</option>
        </select>
      </div>
      <div className="catalog-state-example">
        {state === "empty" ? (
          <Empty title="아직 모은 자료가 없어요">
            키워드를 추가하면 관련 자료를 모을 수 있어요.
          </Empty>
        ) : state === "error" ? (
          <ErrorNotice
            error={new Error("자료를 불러오지 못했어요.")}
            retry={() => setState("empty")}
          />
        ) : state === "loading" ? (
          <Loading />
        ) : (
          <p role="status">저장됐어요.</p>
        )}
      </div>
    </section>
  );
}
