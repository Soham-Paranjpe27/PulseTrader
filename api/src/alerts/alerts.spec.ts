import { AlertCondition } from '@prisma/client';
import { alertFires } from './alerts.service';

describe('alertFires', () => {
  it('price thresholds', () => {
    expect(
      alertFires(
        { condition: AlertCondition.PRICE_ABOVE, threshold: 100 },
        { lastClose: 101, latestDirection: null },
      ),
    ).toBe(true);
    expect(
      alertFires(
        { condition: AlertCondition.PRICE_ABOVE, threshold: 100 },
        { lastClose: 100, latestDirection: null },
      ),
    ).toBe(false);
    expect(
      alertFires(
        { condition: AlertCondition.PRICE_BELOW, threshold: 100 },
        { lastClose: 99, latestDirection: null },
      ),
    ).toBe(true);
    expect(
      alertFires(
        { condition: AlertCondition.PRICE_BELOW, threshold: 100 },
        { lastClose: null, latestDirection: null },
      ),
    ).toBe(false);
  });
  it('prediction direction, never on abstentions', () => {
    expect(
      alertFires(
        { condition: AlertCondition.PREDICTION_UP, threshold: null },
        { lastClose: null, latestDirection: 'UP' },
      ),
    ).toBe(true);
    expect(
      alertFires(
        { condition: AlertCondition.PREDICTION_DOWN, threshold: null },
        { lastClose: null, latestDirection: 'NO_PREDICTION' },
      ),
    ).toBe(false);
  });
});
