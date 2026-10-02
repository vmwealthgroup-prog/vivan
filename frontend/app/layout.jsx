import './globals.css';

export const metadata = {
  title: 'VM Algo - Quantitative Trading & Research Platform',
  description: 'Algorithmic trading strategies and analytics.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="antialiased font-sans bg-slate-950 text-white">{children}</body>
    </html>
  );
}
