import type { Metadata } from 'next';
import { Nav } from '@/components/nav';
import './globals.css';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: { default: 'PulseTrader', template: '%s · PulseTrader' },
  description: 'Indian stock-market direction prediction research platform',
};

// Applies the saved theme before first paint (no flash). Reads only the UI prefs key.
const themeScript = `try{var p=JSON.parse(localStorage.getItem('pulsetrader-prefs')||'{}');document.documentElement.dataset.theme=(p.state&&p.state.theme)||'dark'}catch(e){document.documentElement.dataset.theme='dark'}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen antialiased">
        <Providers>
          <Nav />
          <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">{children}</main>
          <footer className="text-muted-foreground mx-auto max-w-7xl px-4 pb-8 text-xs sm:px-6">
            Research platform. Historical NSE data; predictions are research output, not investment advice.
          </footer>
        </Providers>
      </body>
    </html>
  );
}
