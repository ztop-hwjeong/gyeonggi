import { KeywordEditor } from "@/features/keywords/keyword-editor";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <KeywordEditor id={id} />;
}
