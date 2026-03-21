import type { Metadata } from "next";
import { IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";
import { Sidebar } from "@/components/sidebar";
import { MarketStatusBar } from "@/components/market-status-bar";
import { AnalysisProvider } from "@/context/analysis-context";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthGate } from "@/components/auth-gate";
import { ErrorBoundary } from "@/components/error-boundary";
import "./globals.css";

const ibmPlex = IBM_Plex_Sans({
  variable: "--font-ibm-plex",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
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
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("qp-theme");if(t==="light")return;document.documentElement.classList.add("dark")}catch(e){}})()`,
          }}
        />
      </head>
      <body
        className={`${ibmPlex.variable} ${jetbrainsMono.variable} font-sans antialiased bg-background`}
      >
        <ThemeProvider>
          <AuthGate>
            <ErrorBoundary>
              <AnalysisProvider>
                <Sidebar />
                <main className="min-h-screen transition-all duration-200 ml-0 md:ml-[72px] lg:ml-[250px]">
                  <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-10 py-6 lg:py-8">
                    <MarketStatusBar />
                    {children}
                  </div>
                </main>
              </AnalysisProvider>
            </ErrorBoundary>
          </AuthGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
