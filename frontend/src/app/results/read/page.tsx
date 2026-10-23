import { ArticleReader } from "@/features/results/article-reader";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{
    source?: string;
    source_id?: string;
    return_query?: string;
  }>;
}) {
  const params = await searchParams;
  return (
    <ArticleReader
      source={params.source ?? ""}
      sourceId={params.source_id ?? ""}
      returnQuery={params.return_query ?? ""}
    />
  );
}
