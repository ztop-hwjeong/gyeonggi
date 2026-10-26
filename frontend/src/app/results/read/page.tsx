import { MaterialReader } from "@/features/results/material-reader";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ material_id?: string; return_query?: string }>;
}) {
  const params = await searchParams;
  return (
    <MaterialReader
      materialId={params.material_id ?? ""}
      returnQuery={params.return_query ?? ""}
    />
  );
}
