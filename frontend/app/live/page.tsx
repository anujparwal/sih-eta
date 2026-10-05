import { LiveTrainLookup } from "@/components/live-train-lookup";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ train?: string; date?: string; stop?: string }>;
}) {
  const query = await searchParams;
  return <LiveTrainLookup
    initialStop={typeof query.stop === "string" && query.stop.length <= 80 ? query.stop : ""}
    initialTrain={query.train && /^[0-9]{5}$/.test(query.train) ? query.train : ""}
    initialDate={query.date && /^\d{4}-\d{2}-\d{2}$/.test(query.date) ? query.date : ""}
  />;
}
