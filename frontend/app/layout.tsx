import type { Metadata } from "next";
import { AuthProvider, Header } from "@/components/AuthProvider";
import "./globals.css";
export const metadata: Metadata = {
  title: "Boardom — Room to teach",
  description: "A simple workspace for your lessons and teaching materials.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <a className="skip-link" href="#main">
            Skip to content
          </a>
          <Header />
          <main id="main" className="container">
            {children}
          </main>
          <footer className="site-footer">
            Boardom <span>A little less admin. A little more teaching.</span>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
