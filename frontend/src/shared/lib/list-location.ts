"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

export function useListLocation() {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const rawOffset = Number(params.get("offset") ?? 0);
  const offset =
    Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0;
  function update(values: Record<string, string | number | null>) {
    const next = new URLSearchParams(params.toString());
    if (!("offset" in values)) next.delete("offset");
    for (const [key, value] of Object.entries(values)) {
      if (value === null || value === "" || value === 0) next.delete(key);
      else next.set(key, String(value));
    }
    router.push(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  }
  return { params, offset, update };
}
