import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Discovery",
  description: "Multi-signal stock discovery and early detection tool",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full dark">
      <body className="h-full overflow-hidden">{children}</body>
    </html>
  );
}
