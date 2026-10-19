'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import type { z } from 'zod';
import { ErrorView, PageHeader, RequireAuth } from '@/components/status';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/input';
import { FieldError, Label } from '@/components/ui/label';
import { ME_KEY, useLogout, useMe } from '@/hooks/auth';
import { patch } from '@/lib/api';
import { day } from '@/lib/format';
import { profileSchema } from '@/lib/schemas';
import { type Theme, usePrefs } from '@/lib/store';
import type { User } from '@/lib/types';

function Profile({ user }: { user: User }) {
  const qc = useQueryClient();
  const form = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: { name: user.name ?? '' },
  });
  const save = useMutation({
    mutationFn: (v: { name: string }) => patch<User>('/users/me', v),
    onSuccess: (u) => qc.setQueryData(ME_KEY, u),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
        <CardDescription>
          {user.email} · {user.role} · member since {day(user.createdAt)}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          noValidate
          className="flex flex-wrap items-start gap-3"
          onSubmit={form.handleSubmit((v) => save.mutate(v))}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="name">Display name</Label>
            <Input id="name" className="w-64" {...form.register('name')} />
            <FieldError message={form.formState.errors.name?.message} />
          </div>
          <Button type="submit" className="mt-5" disabled={save.isPending}>
            Save
          </Button>
          {save.isSuccess ? <span className="text-up mt-7 text-xs">Saved</span> : null}
        </form>
        {save.error ? <ErrorView error={save.error} /> : null}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const me = useMe();
  const theme = usePrefs((s) => s.theme);
  const setTheme = usePrefs((s) => s.setTheme);
  const logout = useLogout();
  const router = useRouter();
  return (
    <RequireAuth>
      <PageHeader title="Settings" />
      <div className="flex flex-col gap-4">
        {me.data ? <Profile user={me.data} /> : null}
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>Stored in this browser only.</CardDescription>
          </CardHeader>
          <CardContent>
            <Label htmlFor="theme">Theme</Label>
            <Select
              id="theme"
              className="mt-1 w-40"
              value={theme}
              onChange={(e) => setTheme(e.target.value as Theme)}
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
              <option value="system">System</option>
            </Select>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Session</CardTitle>
            <CardDescription>
              Sessions use httpOnly cookies that rotate on refresh. Logging out revokes this session on the
              server.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="destructive"
              onClick={() => logout.mutate(undefined, { onSettled: () => router.push('/login') })}
            >
              Log out
            </Button>
          </CardContent>
        </Card>
      </div>
    </RequireAuth>
  );
}
