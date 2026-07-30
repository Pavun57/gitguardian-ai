import "./globals.css";
import Nav from "../components/Nav";

export const metadata = {
  title: "GitGuardian AI",
  description: "Agentic security on every push",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main>{children}</main>
      </body>
    </html>
  );
}
