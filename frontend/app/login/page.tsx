import { AuthForm } from "@/components/AuthForm";
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ expired?: string }>;
}) {
  const { expired } = await searchParams;
  return <AuthForm expired={expired === "1"} />;
}
