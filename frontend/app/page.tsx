import { redirect } from 'next/navigation';

export default function Home() {
  // middleware에서 역할별 리다이렉트 처리
  redirect('/login');
}
