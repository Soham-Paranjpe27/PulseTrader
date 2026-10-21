/**
 * Seed the application database from `pulsetrader export-app` output (real data only):
 *   stocks.json   -> Stock (+ SymbolHistory for rename candidates)
 *   day_bars.csv  -> MarketData (daily bars)
 * Optional: ADMIN_EMAIL + ADMIN_PASSWORD create an ADMIN user (never hardcoded).
 * Usage: APP_DATA_DIR=../data/app node dist/seed/seed.js [--bars-universe-only]
 */
import { hash } from '@node-rs/argon2';
import { InstrumentType, PrismaClient } from '@prisma/client';
import { createReadStream, existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

interface StockRow {
  symbol: string;
  instrumentType: InstrumentType;
  experimentEligible: boolean;
  inResearchUniverse: boolean;
  firstDate: string | null;
  lastDate: string | null;
  medianDailyTurnover: number | null;
  sector: string | null;
  renameCandidateOf: string | null;
}

const BATCH = 5000;

async function main(): Promise<void> {
  const dir = process.env.APP_DATA_DIR ?? join(__dirname, '..', '..', '..', 'data', 'app');
  const universeOnly = process.argv.includes('--bars-universe-only');
  const prisma = new PrismaClient();
  try {
    const stocksFile = join(dir, 'stocks.json');
    if (!existsSync(stocksFile))
      throw new Error(`${stocksFile} missing: run \`pulsetrader export-app\` first`);
    const stocks = JSON.parse(readFileSync(stocksFile, 'utf8')) as StockRow[];
    for (let i = 0; i < stocks.length; i += 500) {
      await prisma.$transaction(
        stocks.slice(i, i + 500).map((s) => {
          const data = {
            instrumentType: s.instrumentType,
            experimentEligible: s.experimentEligible,
            inResearchUniverse: s.inResearchUniverse,
            firstDate: s.firstDate ? new Date(s.firstDate) : null,
            lastDate: s.lastDate ? new Date(s.lastDate) : null,
            medianDailyTurnover: s.medianDailyTurnover,
            sector: s.sector,
          };
          return prisma.stock.upsert({
            where: { symbol: s.symbol },
            create: { symbol: s.symbol, ...data },
            update: data,
          });
        }),
      );
    }
    await prisma.symbolHistory.deleteMany({});
    await prisma.symbolHistory.createMany({
      data: stocks
        .filter((s) => s.renameCandidateOf)
        .map((s) => ({
          symbol: s.symbol,
          oldSymbol: s.renameCandidateOf,
          note: 'rename candidate (Phase 3 heuristic)',
        })),
    });
    console.log(`stocks: ${stocks.length}`);

    const allowed = new Set(
      stocks
        .filter((s) => !universeOnly || s.inResearchUniverse || s.instrumentType === 'INDEX')
        .map((s) => s.symbol),
    );
    const lines = createInterface({
      input: createReadStream(join(dir, 'day_bars.csv')),
      crlfDelay: Infinity,
    });
    let header: string[] | null = null;
    let batch: {
      symbol: string;
      tradeDate: Date;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
    }[] = [];
    let n = 0;
    const flush = async () => {
      if (!batch.length) return;
      n += (await prisma.marketData.createMany({ data: batch, skipDuplicates: true })).count;
      batch = [];
    };
    for await (const line of lines) {
      const f = line.split(',');
      if (!header) {
        header = f;
        if (header.join(',') !== 'symbol,trade_date,open,high,low,close,volume')
          throw new Error(`unexpected CSV header ${line}`);
        continue;
      }
      // symbols never contain commas in this dataset; validate the column count anyway
      if (f.length !== 7) throw new Error(`bad CSV row: ${line}`);
      if (!allowed.has(f[0])) continue;
      const nums = f.slice(2).map(Number);
      if (nums.some((x) => !Number.isFinite(x))) continue; // null OHLC in source: skip, counted below
      batch.push({
        symbol: f[0],
        tradeDate: new Date(f[1]),
        open: nums[0],
        high: nums[1],
        low: nums[2],
        close: nums[3],
        volume: nums[4],
      });
      if (batch.length >= BATCH) await flush();
    }
    await flush();
    console.log(`market data rows inserted: ${n}`);

    if (process.env.ADMIN_EMAIL && process.env.ADMIN_PASSWORD) {
      const email = process.env.ADMIN_EMAIL.toLowerCase();
      await prisma.user.upsert({
        where: { email },
        create: {
          email,
          role: 'ADMIN',
          passwordHash: await hash(process.env.ADMIN_PASSWORD, {
            memoryCost: 19456,
            timeCost: 2,
            parallelism: 1,
          }),
        },
        update: { role: 'ADMIN' },
      });
      console.log(`admin user ${email} ready`);
    }
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((e: unknown) => {
  console.error(e);
  process.exit(1);
});
