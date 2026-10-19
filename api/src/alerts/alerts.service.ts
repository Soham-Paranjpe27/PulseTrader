import { Alert, AlertCondition } from '@prisma/client';

export interface AlertInputs {
  lastClose: number | null;
  latestDirection: string | null;
}

/** Pure rule: does this alert fire for the given latest close / latest prediction direction? */
export function alertFires(a: Pick<Alert, 'condition' | 'threshold'>, x: AlertInputs): boolean {
  switch (a.condition) {
    case AlertCondition.PRICE_ABOVE:
      return x.lastClose !== null && a.threshold !== null && x.lastClose > a.threshold;
    case AlertCondition.PRICE_BELOW:
      return x.lastClose !== null && a.threshold !== null && x.lastClose < a.threshold;
    case AlertCondition.PREDICTION_UP:
      return x.latestDirection === 'UP';
    case AlertCondition.PREDICTION_DOWN:
      return x.latestDirection === 'DOWN';
    default:
      return false;
  }
}
