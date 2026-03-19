import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Sidebar } from "@/components/sidebar";
import { MarketStatusBar } from "@/components/market-status-bar";
import { ScanProvider } from "@/context/scan-context";
import { AnalysisProvider } from "@/context/analysis-context";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "QuantPulse v3",
  description:
    "Multi-strategy quantitative trading advisory system — signal generation and decision cockpit",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased bg-background`}
      >
        <ScanProvider>
          <AnalysisProvider>
            <Sidebar />
            <main className="ml-[250px] min-h-screen transition-all duration-200">
              <div className="max-w-[1400px] mx-auto px-10 py-8">
                <MarketStatusBar />
                {children}
              </div>
            </main>
          </AnalysisProvider>
        </ScanProvider>
      </body>
    </html>
  );
}
