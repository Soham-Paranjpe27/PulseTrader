import { z } from 'zod';

/** Form schemas. They mirror the API's validation so users see errors before a round trip. */

export const SYMBOL_RE = /^[A-Za-z0-9&._ -]{1,40}$/;
const symbol = z.string().trim().min(1, 'Enter a symbol').regex(SYMBOL_RE, 'Not a valid symbol');

export const loginSchema = z.object({
  email: z.string().trim().email('Enter a valid email'),
  password: z.string().min(1, 'Enter your password'),
});
export type LoginInput = z.infer<typeof loginSchema>;

export const registerSchema = z
  .object({
    name: z.string().trim().max(100).optional(),
    email: z.string().trim().email('Enter a valid email'),
    password: z
      .string()
      .min(12, 'At least 12 characters')
      .max(128, 'At most 128 characters')
      .regex(/[A-Za-z]/, 'Needs a letter')
      .regex(/\d/, 'Needs a digit'),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' });
export type RegisterInput = z.infer<typeof registerSchema>;

export const watchlistSchema = z.object({ name: z.string().trim().min(1, 'Name it').max(60) });
export const addSymbolSchema = z.object({ symbol });

export const alertSchema = z
  .object({
    symbol,
    condition: z.enum(['PRICE_ABOVE', 'PRICE_BELOW', 'PREDICTION_UP', 'PREDICTION_DOWN']),
    threshold: z.coerce.number().positive('Must be positive').optional(),
  })
  .refine((v) => !v.condition.startsWith('PRICE') || v.threshold !== undefined, {
    path: ['threshold'],
    message: 'Price alerts need a price',
  });
export type AlertInput = z.infer<typeof alertSchema>;

export const portfolioSchema = z.object({
  name: z.string().trim().min(1, 'Name it').max(60),
  cash: z.coerce.number().positive('Must be positive').max(1e12),
});

export const tradeSchema = z.object({
  symbol,
  side: z.enum(['BUY', 'SELL']),
  quantity: z.coerce.number().positive('Must be positive').max(1e9),
});

/** Historical prediction request: an IST wall-clock time inside the regular session. */
export const predictionSchema = z
  .object({
    modelId: z.string().min(1, 'Pick a model'),
    date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Pick a date'),
    time: z.string().regex(/^\d{2}:\d{2}$/, 'Pick a time'),
  })
  .refine((v) => v.time >= '09:15' && v.time <= '15:29', {
    path: ['time'],
    message: 'NSE regular session is 09:15–15:30 IST',
  });
export type PredictionInput = z.infer<typeof predictionSchema>;

/** The bar-start timestamp the ML service expects, with the IST offset. */
export function istTimestamp(date: string, time: string): string {
  return `${date}T${time}:00+05:30`;
}

export const askSchema = z.object({ question: z.string().trim().min(3, 'Ask a question').max(500) });
export const profileSchema = z.object({ name: z.string().trim().max(100) });
