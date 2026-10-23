import type { Metadata } from "next";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./globals.css";
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
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
