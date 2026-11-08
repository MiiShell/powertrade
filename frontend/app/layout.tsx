import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PowerTrade",
  description: "Self-hosted charting & stock research",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
