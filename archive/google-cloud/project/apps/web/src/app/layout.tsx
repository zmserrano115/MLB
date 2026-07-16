import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import "@all-rise/ui/tokens.css";
import "../styles/globals.css";

import { SiteNavigation } from "../components/site-navigation";

const description =
  "MLB schedules, matchups, weather, streaks, and player research in one analytical workspace.";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const forwardedProto = requestHeaders.get("x-forwarded-proto");
  const protocol = forwardedProto === "http" ? "http" : "https";
  const host = requestHeaders.get("x-forwarded-host") || requestHeaders.get("host") || "localhost:3000";
  const baseUrl = new URL(process.env.SITE_URL || `${protocol}://${host}`);
  const imageUrl = new URL("/og.png", baseUrl).toString();
  return {
    metadataBase: baseUrl,
    title: { default: "All Rise Analytics", template: "%s | All Rise Analytics" },
    description,
    openGraph: {
      title: "All Rise Analytics",
      description: "Baseball intelligence, without the guesswork.",
      type: "website",
      images: [{ url: imageUrl, width: 1744, height: 909, alt: "All Rise Analytics" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "All Rise Analytics",
      description: "Baseball intelligence, without the guesswork.",
      images: [imageUrl],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <SiteNavigation />
        <div className="site-content">{children}</div>
        <footer className="site-footer">
          <span>All Rise Analytics</span>
          <span>Provider data can change after official scoring corrections.</span>
        </footer>
      </body>
    </html>
  );
}
