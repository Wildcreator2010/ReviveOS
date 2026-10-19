import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "../components/layout/AppShell";
import { ApiStatusChip } from "../src/api/apiStatus";

export const metadata: Metadata = {
  title: "ReviveOS · Software ICU",
  description: "可追溯的软件复生控制台：考古、修复、行为比对与复生评分。",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0a0f1c",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <AppShell headerStatus={<ApiStatusChip />}>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
