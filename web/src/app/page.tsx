import Link from 'next/link';
import { ModelsTable } from '@/components/models-table';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const FACTS = [
  { k: 'Instruments', v: '2,535', d: 'NSE equities, ETFs and indices' },
  { k: 'Minute bars', v: '713M', d: '2022-01-03 to 2026-01-21' },
  { k: 'Daily bars', v: '7.0M', d: 'from 2000-01-01' },
  { k: 'Features', v: '84', d: 'one shared engine for training and live' },
];

export default function Home() {
  return (
    <div className="flex flex-col gap-8">
      <section className="mt-4 flex flex-col gap-4">
        <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
          Short-horizon direction research for Indian stocks, with the evidence shown as measured.
        </h1>
        <p className="text-muted-foreground max-w-2xl">
          PulseTrader trains direction models on real NSE minute data with leakage-safe, chronological
          validation. Every result is reported with balanced accuracy, MCC and coverage, and predictions from
          models that have not passed every production gate are labelled research only.
        </p>
        <div className="flex gap-2">
          <Button asChild>
            <Link href="/stocks">Browse stocks</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/dashboard">Open dashboard</Link>
          </Button>
        </div>
      </section>
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {FACTS.map((f) => (
          <Card key={f.k}>
            <CardHeader>
              <CardDescription>{f.k}</CardDescription>
              <CardTitle className="text-2xl">{f.v}</CardTitle>
            </CardHeader>
            <CardContent className="text-muted-foreground text-xs">{f.d}</CardContent>
          </Card>
        ))}
      </section>
      <Card>
        <CardHeader>
          <CardTitle>Registered models</CardTitle>
          <CardDescription>
            Validation period metrics from the model registry (test period still untouched). The 70–80%
            accuracy target is not verified.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ModelsTable />
        </CardContent>
      </Card>
    </div>
  );
}
