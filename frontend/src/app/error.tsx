"use client";
import { ErrorNotice } from "@/shared/ui/feedback";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <ErrorNotice
      error={
        new globalThis.Error("화면을 표시하지 못했어요. 다시 시도해 주세요.")
      }
      retry={reset}
    />
  );
}
