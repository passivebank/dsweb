import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Portfolio — DomainSnobs",
  description:
    "Select domains currently available for acquisition. Inquire for pricing on unlisted inventory.",
};

export default function PortfolioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
