import { RunCreate } from "@/features/runs/run-create";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{
    rule?: string;
    source?: string;
    mode?: string;
    start?: string;
    end?: string;
    repeat?: string;
  }>;
}) {
  const params = await searchParams;
  return (
    <RunCreate
      initialRule={params.rule}
      initialSource={params.source}
      initialMode={params.mode}
      initialStart={params.start}
      initialEnd={params.end}
      repeated={params.repeat === "1"}
    />
  );
}
