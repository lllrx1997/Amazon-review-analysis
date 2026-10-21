import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Review Lens · 亚马逊评论洞察", description: "从买家原声中发现产品问题与认可点，每个洞察都有评论证据。" };

export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
