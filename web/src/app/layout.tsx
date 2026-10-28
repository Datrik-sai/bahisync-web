import type { Metadata } from "next";
import "@fontsource-variable/public-sans";
import "./globals.css";

export const metadata: Metadata = {
  title: "BahiSync — Bank statement PDF to Tally",
  description:
    "Turn any Indian bank statement PDF into Tally vouchers. Every row is checked against the running balance, so nothing is missed or misread.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
