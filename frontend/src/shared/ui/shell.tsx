"use client";

import {
  ChartLineUpIcon,
  ClockCounterClockwiseIcon,
  DatabaseIcon,
  GearSixIcon,
  ListIcon,
  MagnifyingGlassIcon,
  XIcon,
} from "@phosphor-icons/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";

const navigation = [
  { href: "/", label: "수집 현황", icon: ChartLineUpIcon },
  { href: "/keywords", label: "키워드 관리", icon: MagnifyingGlassIcon },
  { href: "/runs", label: "수집 이력", icon: ClockCounterClockwiseIcon },
  { href: "/results", label: "수집 자료", icon: DatabaseIcon },
  { href: "/workers", label: "수집 환경", icon: GearSixIcon },
];

export function Shell({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [open]);
  return (
    <QueryClientProvider client={queryClient}>
      <a className="skip-link" href="#main">
        본문으로 이동
      </a>
      <aside className={`sidebar ${open ? "open" : ""}`} id="navigation">
        <button
          ref={closeButton}
          type="button"
          className="button icon-button sidebar-close"
          aria-label="메뉴 닫기"
          onClick={() => setOpen(false)}
        >
          <XIcon size={22} />
        </button>
        <Link href="/" className="brand" onClick={() => setOpen(false)}>
          <span className="brand-mark">
            <ChartLineUpIcon size={25} weight="bold" />
          </span>
          <span>
            경기교육<span className="brand-sub">정책 홍보 모니터링</span>
          </span>
        </Link>
        <div className="workspace-name">수집 관리</div>
        <nav aria-label="주 메뉴">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/" ? pathname === href : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={active ? "active" : ""}
                aria-current={active ? "page" : undefined}
                onClick={() => setOpen(false)}
              >
                <Icon size={21} weight={active ? "fill" : "regular"} />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <span className="workspace-avatar">경</span>
          <div>
            <strong>경기교육 정책 분석</strong>
            <span>내부 운영 공간</span>
          </div>
        </div>
      </aside>
      {open && (
        <button
          className="nav-overlay"
          type="button"
          aria-label="메뉴 닫기"
          onClick={() => setOpen(false)}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <button
            className="button icon-button menu-toggle"
            type="button"
            aria-label={open ? "메뉴 닫기" : "메뉴 열기"}
            aria-expanded={open}
            aria-controls="navigation"
            onClick={() => setOpen(!open)}
          >
            {open ? <XIcon size={22} /> : <ListIcon size={22} />}
          </button>
          <span>경기교육 정책 홍보 분석</span>
          <span className="topbar-note">수집 운영</span>
        </header>
        <main id="main" className="main-content">
          {children}
        </main>
        <footer className="workspace-footer">
          경기도교육청 정책 홍보 현황 및 성과 분석
        </footer>
      </div>
    </QueryClientProvider>
  );
}
