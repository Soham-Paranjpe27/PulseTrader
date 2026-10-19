import { parseQuestion } from './intent';

const known = new Set(['TCS', 'RELIANCE', 'INFY']);

describe('parseQuestion', () => {
  it.each([
    ['What is the latest prediction for TCS?', { kind: 'LATEST_PREDICTION', symbol: 'TCS' }],
    ['Why did the model predict DOWN for RELIANCE?', { kind: 'WHY_PREDICTION', symbol: 'RELIANCE' }],
    ['How accurate has the model been recently?', { kind: 'ACCURACY', symbol: null }],
    ['Compare RELIANCE and INFY.', { kind: 'COMPARE', symbols: ['RELIANCE', 'INFY'] }],
    ['Which features influenced the prediction?', { kind: 'FEATURES', symbol: null }],
    ['Tell me a joke', { kind: 'UNSUPPORTED' }],
    ['latest prediction for UNKNOWNCO', { kind: 'UNSUPPORTED' }],
  ])('%s', (q, want) => expect(parseQuestion(q, known)).toEqual(want));

  it('ignores the direction word DOWN as a symbol', () => {
    expect(parseQuestion('why DOWN on TCS', known)).toEqual({ kind: 'WHY_PREDICTION', symbol: 'TCS' });
  });
});
