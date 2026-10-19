'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import type { z } from 'zod';
import { ErrorView, PageHeader, RequireAuth } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { FieldError } from '@/components/ui/label';
import { post } from '@/lib/api';
import { askSchema } from '@/lib/schemas';
import type { ResearchAnswer } from '@/lib/types';

const EXAMPLES = [
  'What is the latest prediction for RELIANCE?',
  'Why did the model predict DOWN for TCS?',
  'How accurate has the model been recently?',
  'Compare RELIANCE and INFY',
  'Which features influenced the prediction for HDFCBANK?',
];

interface Turn {
  q: string;
  a: ResearchAnswer;
}

function Assistant() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const form = useForm<z.infer<typeof askSchema>>({
    resolver: zodResolver(askSchema),
    defaultValues: { question: '' },
  });
  const ask = useMutation({
    mutationFn: (question: string) => post<ResearchAnswer>('/research/ask', { question }),
    onSuccess: (a, q) => {
      setTurns((t) => [{ q, a }, ...t]);
      form.reset();
    },
  });
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Ask about stored data</CardTitle>
          <CardDescription>
            Answers come only from the application database (predictions, prices, models). When the data is
            not there the answer says DATA_UNAVAILABLE; questions it cannot parse return UNSUPPORTED.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <form noValidate className="flex gap-2" onSubmit={form.handleSubmit((v) => ask.mutate(v.question))}>
            <div className="flex flex-1 flex-col gap-1">
              <Input aria-label="Question" placeholder="Ask a question" {...form.register('question')} />
              <FieldError message={form.formState.errors.question?.message} />
            </div>
            <Button type="submit" disabled={ask.isPending}>
              {ask.isPending ? 'Asking…' : 'Ask'}
            </Button>
          </form>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((e) => (
              <button
                key={e}
                type="button"
                className="border-border text-muted-foreground hover:bg-accent rounded-md border px-2 py-1 text-xs"
                onClick={() => ask.mutate(e)}
              >
                {e}
              </button>
            ))}
          </div>
          {ask.error ? <ErrorView error={ask.error} /> : null}
        </CardContent>
      </Card>
      <div className="flex flex-col gap-3" data-testid="answers">
        {turns.map((t, i) => (
          <Card key={turns.length - i}>
            <CardContent className="flex flex-col gap-2 pt-4">
              <p className="text-sm font-medium">{t.q}</p>
              <div className="flex items-center gap-2">
                <Badge
                  tone={t.a.status === 'OK' ? 'up' : t.a.status === 'DATA_UNAVAILABLE' ? 'warn' : 'neutral'}
                  data-testid="answer-status"
                >
                  {t.a.status}
                </Badge>
                <span className="text-muted-foreground text-xs">intent {t.a.intent.kind}</span>
              </div>
              <p className="text-sm whitespace-pre-line" data-testid="answer">
                {t.a.answer}
              </p>
              {t.a.sources?.length ? (
                <p className="text-muted-foreground text-xs">Sources: {t.a.sources.join(', ')}</p>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function ResearchPage() {
  return (
    <RequireAuth>
      <PageHeader
        title="Research assistant"
        description="Questions answered from verified application data only."
      />
      <Assistant />
    </RequireAuth>
  );
}
