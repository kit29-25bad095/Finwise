import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Finora — AI-Powered Financial Reconciliation & Revenue Leakage Engine",
  description: "Deterministic three-way financial reconciliation and automated dispute intelligence for Indian D2C brands.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-background text-slate-100 antialiased selection:bg-sky-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
