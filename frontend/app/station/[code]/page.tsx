import { notFound } from "next/navigation";
import { StationBoard } from "@/components/station-board";
export default async function Page({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  if (!/^[A-Z0-9]{1,10}$/.test(code)) notFound();
  return <StationBoard key={code} code={code} />;
}
