import { Global, Module } from '@nestjs/common';
import { APP_INTERCEPTOR } from '@nestjs/core';
import { LatencyInterceptor, LatencyRecorder } from './latency';
import { MonitoringController } from './monitoring.controller';
import { MonitoringService } from './monitoring.service';

@Global()
@Module({
  controllers: [MonitoringController],
  providers: [LatencyRecorder, MonitoringService, { provide: APP_INTERCEPTOR, useClass: LatencyInterceptor }],
  exports: [MonitoringService, LatencyRecorder],
})
export class MonitoringModule {}
