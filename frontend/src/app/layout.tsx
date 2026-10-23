import type { Metadata } from "next";
import { Suspense } from "react";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./globals.css";
import { Loading } from "@/shared/ui/feedback";
import { Shell } from "@/shared/ui/shell";

export const metadata: Metadata = {
  title: "경기교육 | 정책 홍보 모니터링",
  description: "경기교육 정책 키워드와 수집 운영 관리",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>
        <Shell>
          <Suspense fallback={<Loading />}>{children}</Suspense>
        </Shell>
      </body>
    </html>
  );
}
