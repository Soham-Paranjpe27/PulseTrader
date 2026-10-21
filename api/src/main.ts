import { Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { configureApp } from './setup';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule);
  configureApp(app);
  const port = app.get(ConfigService).getOrThrow<number>('PORT');
  await app.listen(port);
  Logger.log(`PulseTrader API on :${port} (docs at /api/docs)`, 'bootstrap');
}

bootstrap().catch((e: unknown) => {
  Logger.error(`startup failed: ${(e as Error).message}`, 'bootstrap');
  process.exit(1);
});
