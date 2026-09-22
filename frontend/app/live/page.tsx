import { LiveTrainLookup } from "@/components/live-train-lookup";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ train?: string; date?: string }>;
}) {
  const query = await searchParams;
  return <LiveTrainLookup
    initialTrain={query.train && /^[0-9]{5}$/.test(query.train) ? query.train : ""}
    initialDate={query.date && /^\d{4}-\d{2}-\d{2}$/.test(query.date) ? query.date : ""}
  />;
}
