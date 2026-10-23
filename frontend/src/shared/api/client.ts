"use client";

import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import type { components } from "./schema";

export type Schema = components["schemas"];

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new Error("서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : response.status === 422
          ? "입력한 조건을 확인해 주세요. 검색어와 날짜 범위가 올바른지 확인해 주세요."
          : "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.",
    );
  }
  return response.json() as Promise<T>;
}

export function useApi<T>(path: string | null, refresh = true) {
  return useQuery({
    queryKey: [path],
    queryFn: ({ signal }) => api<T>(path as string, { signal }),
    enabled: path !== null,
    staleTime: 10_000,
    refetchInterval: refresh ? 15_000 : false,
    retry: 1,
  });
}

export function post<T>(path: string, body: unknown, key?: string) {
  return api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: key ? { "Idempotency-Key": key } : {},
  });
}

export function useIdempotentPost<T>() {
  const pending = useRef<{ fingerprint: string; key: string } | null>(null);
  return async (path: string, body: unknown) => {
    const fingerprint = JSON.stringify([path, body]);
    if (pending.current?.fingerprint !== fingerprint) {
      pending.current = { fingerprint, key: crypto.randomUUID() };
    }
    const result = await post<T>(path, body, pending.current.key);
    pending.current = null;
    return result;
  };
}
