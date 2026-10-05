import { Passenger } from "@/components/passenger";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ train?: string }>;
}) {
  const { train } = await searchParams;
  const initial = train && /^\d{5}$/.test(train) ? train : "12301";
  return <Passenger key={initial} initialTrain={initial} />;
}
