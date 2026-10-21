import { Body, Controller, Injectable, Module, Post } from '@nestjs/common';
import { ApiProperty, ApiTags } from '@nestjs/swagger';
import { IsString, MaxLength, MinLength } from 'class-validator';
import { PrismaService } from '../prisma/prisma.service';
import { PredictionsService } from '../predictions/predictions.service';
import { PredictionsModule } from '../predictions/predictions.module';
import { parseQuestion } from './intent';

class AskDto {
  @ApiProperty({ example: 'What is the latest prediction for TCS?' })
  @IsString()
  @MinLength(3)
  @MaxLength(500)
  question: string;
}

const UNAVAILABLE = 'DATA_UNAVAILABLE';

@Injectable()
export class ResearchService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly preds: PredictionsService,
  ) {}

  private async snapshot(symbol: string) {
    const [bar, pred] = await Promise.all([
      this.prisma.marketData.findFirst({ where: { symbol }, orderBy: { tradeDate: 'desc' } }),
      this.prisma.prediction.findFirst({ where: { symbol }, orderBy: { predictionTimestamp: 'desc' } }),
    ]);
    return { bar, pred };
  }

  async ask(question: string) {
    const known = new Set(
      (await this.prisma.stock.findMany({ select: { symbol: true } })).map((s) => s.symbol),
    );
    const intent = parseQuestion(question, known);
    const sources: string[] = [];
    switch (intent.kind) {
      case 'LATEST_PREDICTION': {
        const { pred } = await this.snapshot(intent.symbol);
        if (!pred)
          return { intent, status: UNAVAILABLE, answer: `No stored prediction for ${intent.symbol}.` };
        sources.push(`prediction:${pred.id}`);
        const p = pred.rawProbability as Record<string, number>;
        return {
          intent,
          status: 'OK',
          answer:
            `Latest prediction for ${intent.symbol} (market data ${pred.marketDataTimestamp.toISOString()}, horizon ` +
            `${pred.horizonMinutes} min): ${pred.direction}` +
            (pred.abstainReason ? ` (abstained: ${pred.abstainReason})` : '') +
            `. Raw P(up/neutral/down) = ${fmt(p.up)}/${fmt(p.neutral)}/${fmt(p.down)}. Model ${pred.modelVersionId}` +
            ` (${pred.modelStatus}${pred.researchOnly ? ', research only' : ''}).`,
          data: pred,
          sources,
        };
      }
      case 'WHY_PREDICTION':
      case 'FEATURES': {
        const fv = await this.prisma.featureVersion.findFirst({ orderBy: { createdAt: 'desc' } });
        return {
          intent,
          status: UNAVAILABLE,
          answer:
            'Per-prediction feature attributions are not stored, so I cannot say which features drove this prediction. ' +
            (fv
              ? `The model uses ${fv.count} features (${fv.version}); see /api/features/versions/${fv.version}.`
              : ''),
          sources: fv ? [`feature_version:${fv.version}`] : [],
        };
      }
      case 'ACCURACY': {
        const acc = await this.preds.accuracy(intent.symbol ?? undefined);
        if (!acc.evaluated) {
          return {
            intent,
            status: UNAVAILABLE,
            answer:
              `No evaluated prediction outcomes yet${intent.symbol ? ` for ${intent.symbol}` : ''} ` +
              `(${acc.predictions} predictions stored, ${acc.directional} directional). Live evaluation starts in Phase 18; ` +
              'research validation metrics are on /api/models.',
            data: acc,
          };
        }
        return {
          intent,
          status: 'OK',
          answer: `Rolling direction accuracy: ${JSON.stringify(acc.rolling)}`,
          data: acc,
        };
      }
      case 'COMPARE': {
        const [a, b] = await Promise.all(intent.symbols.map((s) => this.snapshot(s)));
        const line = (s: string, x: typeof a) =>
          x.bar
            ? `${s}: close ${x.bar.close.toFixed(2)} on ${x.bar.tradeDate.toISOString().slice(0, 10)}, latest prediction ` +
              `${x.pred ? x.pred.direction : UNAVAILABLE}`
            : `${s}: ${UNAVAILABLE}`;
        return {
          intent,
          status: a.bar && b.bar ? 'OK' : UNAVAILABLE,
          answer: `${line(intent.symbols[0], a)}. ${line(intent.symbols[1], b)}.`,
          data: { [intent.symbols[0]]: a, [intent.symbols[1]]: b },
        };
      }
      default:
        return {
          intent,
          status: 'UNSUPPORTED',
          answer:
            'I can answer: latest prediction for a symbol, why a prediction was made, recent accuracy, comparing two ' +
            'symbols, and which features the model uses. I only use stored application data.',
        };
    }
  }
}

function fmt(x: number | undefined): string {
  return typeof x === 'number' ? x.toFixed(3) : UNAVAILABLE;
}

@ApiTags('research')
@Controller('research')
export class ResearchController {
  constructor(private readonly svc: ResearchService) {}

  @Post('ask')
  ask(@Body() dto: AskDto) {
    return this.svc.ask(dto.question);
  }
}

@Module({ imports: [PredictionsModule], controllers: [ResearchController], providers: [ResearchService] })
export class ResearchModule {}
