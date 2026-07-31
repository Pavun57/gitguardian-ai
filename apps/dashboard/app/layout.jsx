import "./globals.css";
import Nav from "../components/Nav";

export const metadata = {
  title: "GitGuardian AI",
  description: "Agentic security on every commit — local-first",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      {/* suppressHydrationWarning: browser extensions (e.g. Grammarly) inject
          attributes into <body> before React hydrates — harmless */}
      <body suppressHydrationWarning>
        <Nav />
        <main>{children}</main>
      </body>
    </html>
  );
}
