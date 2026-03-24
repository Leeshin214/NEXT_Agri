import type { Metadata } from 'next';
import QueryProvider from '@/components/providers/QueryProvider';
import './globals.css';

export const metadata: Metadata = {
  title: 'AgriFlow - 농산물 유통 B2B 플랫폼',
  description: '농산물 유통업 판매자와 구매자를 연결하는 B2B 업무 웹플랫폼',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-gray-50 antialiased">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
