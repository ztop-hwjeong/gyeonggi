import { RunCreate } from "@/features/runs/run-create";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ rule?: string }>;
}) {
  const { rule } = await searchParams;
  return <RunCreate initialRule={rule} />;
}
