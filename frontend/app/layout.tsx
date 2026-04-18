import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "ValueBet · Arbitraje",
  description: "Surebets detectadas en tiempo real",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
