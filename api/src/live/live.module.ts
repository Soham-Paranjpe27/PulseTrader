import { Global, Module } from '@nestjs/common';
import { PredictionsModule } from '../predictions/predictions.module';
import { IngestTokenGuard, LiveController } from './live.controller';
import { LiveService } from './live.service';

@Global()
@Module({
  imports: [PredictionsModule],
  controllers: [LiveController],
  providers: [LiveService, IngestTokenGuard],
  exports: [LiveService],
})
export class LiveModule {}
