export const number = (value: number | undefined | null) =>
  value == null ? "—" : new Intl.NumberFormat("ko-KR").format(value);

export function dateTime(value: string | undefined | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function today() {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(
    new Date(),
  );
}

export const sourceNames: Record<string, string> = {
  bigkinds: "빅카인즈",
  naver_news: "네이버 뉴스",
  naver_blog: "네이버 블로그",
  naver_cafearticle: "네이버 카페",
};

export const stateNames: Record<string, string> = {
  queued: "실행 대기",
  submitted: "worker 대기",
  running: "수집 중",
  completed: "완료",
  partial: "일부 수집",
  failed: "실패",
  cancelled: "취소됨",
  cancelling: "취소 중",
};

export const modeNames: Record<string, string> = {
  preview: "미리보기",
  incremental: "증분 수집",
  backfill: "과거 수집",
};

export function safeUrl(value: string | null | undefined) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
