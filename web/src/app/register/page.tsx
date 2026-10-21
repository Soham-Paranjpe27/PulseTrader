'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { ErrorView } from '@/components/status';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { FieldError, Label } from '@/components/ui/label';
import { useRegister } from '@/hooks/auth';
import { type RegisterInput, registerSchema } from '@/lib/schemas';

export default function RegisterPage() {
  const router = useRouter();
  const reg = useRegister();
  const form = useForm<RegisterInput>({
    resolver: zodResolver(registerSchema),
    defaultValues: { name: '', email: '', password: '', confirm: '' },
  });
  const e = form.formState.errors;
  const field = (id: keyof RegisterInput, label: string, type: string, auto: string) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type={type} autoComplete={auto} {...form.register(id)} />
      <FieldError message={e[id]?.message} />
    </div>
  );
  return (
    <div className="mx-auto mt-10 max-w-sm">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Create an account</CardTitle>
          <CardDescription>Passwords need 12+ characters with a letter and a digit.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            noValidate
            className="flex flex-col gap-3"
            onSubmit={form.handleSubmit((v) =>
              reg.mutate(v, { onSuccess: () => router.push('/login?registered=1') }),
            )}
          >
            {field('name', 'Name (optional)', 'text', 'name')}
            {field('email', 'Email', 'email', 'email')}
            {field('password', 'Password', 'password', 'new-password')}
            {field('confirm', 'Confirm password', 'password', 'new-password')}
            <ErrorView error={reg.error} title="Registration failed" />
            <Button type="submit" disabled={reg.isPending}>
              {reg.isPending ? 'Creating…' : 'Create account'}
            </Button>
            <p className="text-muted-foreground text-center text-xs">
              Have an account?{' '}
              <Link className="text-primary hover:underline" href="/login">
                Log in
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
