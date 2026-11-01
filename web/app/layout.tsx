import type { Metadata, Viewport } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const serif = Instrument_Serif({ variable: "--font-serif", subsets: ["latin"], weight: "400", style: ["normal", "italic"] });

export const metadata: Metadata = {
  title: "nonce",
  description: "Let AI help with your email, calendar, files and Slack without handing it the keys.",
  appleWebApp: { capable: true, title: "nonce", statusBarStyle: "default" },
  icons: { apple: "/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: "#f6f2eb",
  viewportFit: "cover",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${serif.variable} h-full`}>
      <body className="min-h-full bg-canvas text-[14px] text-ink">{children}</body>
    </html>
  );
}
