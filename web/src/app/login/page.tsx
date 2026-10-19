import type { Metadata } from 'next';
import { Suspense } from 'react';
import { LoginForm } from './login-form';

export const metadata: Metadata = { title: 'Log in' };

export default function LoginPage() {
  return (
    <div className="mx-auto mt-10 max-w-sm">
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
