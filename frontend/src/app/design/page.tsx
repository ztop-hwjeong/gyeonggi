import type { Metadata } from "next";
import { DesignCatalog } from "@/features/design/catalog";

export const metadata: Metadata = { title: "화면 디자인 기준 | 경기교육" };
export default function Page() {
  return <DesignCatalog />;
}
