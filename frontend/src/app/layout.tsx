import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Since You Last Looked — Groww",
  description:
    "A time-aware market watchlist that remembers what you saw and tells you what meaningfully changed since.",
};

// Next 15+ wants themeColor here, not in metadata; keeping it in metadata warns on every build.
export const viewport: Viewport = {
  themeColor: "#00D09C",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
