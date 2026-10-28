import { ReviewScreen } from "./ReviewScreen";

export default async function ReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ client?: string }>;
}) {
  const { id } = await params;
  const { client } = await searchParams;
  return <ReviewScreen id={id} clientName={client ?? ""} />;
}
