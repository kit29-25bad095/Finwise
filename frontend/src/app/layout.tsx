import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine",
  description: "Enterprise three-way financial ledger matching, contractual tariff overcharge detection, and dispute intelligence for Indian D2C enterprises.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-canvas text-ink-primary antialiased">
        {children}
      </body>
    </html>
  );
}
