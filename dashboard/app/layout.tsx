import './globals.css';

export const metadata = { title: 'OpsPilot Evaluation', description: 'Production AI incident-response agent metrics' };

export default function RootLayout({children}:{children:React.ReactNode}) {
  return <html lang="en"><body>{children}</body></html>;
}
