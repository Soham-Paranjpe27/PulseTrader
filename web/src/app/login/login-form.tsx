'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { ErrorView } from '@/components/status';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { FieldError, Label } from '@/components/ui/label';
import { useLogin } from '@/hooks/auth';
import { safeNext } from '@/lib/redirect';
import { type LoginInput, loginSchema } from '@/lib/schemas';

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const login = useLogin();
  const form = useForm<LoginInput>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });
  const e = form.formState.errors;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Log in</CardTitle>
        <CardDescription>
          {params.get('registered') ? 'Account created. Log in to continue.' : 'Welcome back.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          noValidate
          className="flex flex-col gap-3"
          onSubmit={form.handleSubmit((v) =>
            login.mutate(v, { onSuccess: () => router.push(safeNext(params.get('next'))) }),
          )}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="email" {...form.register('email')} />
            <FieldError message={e.email?.message} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              {...form.register('password')}
            />
            <FieldError message={e.password?.message} />
          </div>
          <ErrorView error={login.error} title="Login failed" />
          <Button type="submit" disabled={login.isPending}>
            {login.isPending ? 'Logging in…' : 'Log in'}
          </Button>
          <p className="text-muted-foreground text-center text-xs">
            No account?{' '}
            <Link className="text-primary hover:underline" href="/register">
              Register
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
