import { INestApplication, ValidationPipe } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import cookieParser from 'cookie-parser';
import helmet from 'helmet';

/** Shared HTTP setup for main.ts and the e2e tests (so tests run the real middleware stack). */
export function configureApp(app: INestApplication): void {
  const config = app.get(ConfigService);
  app.setGlobalPrefix('api');
  // Behind the web app's same-origin proxy (or a load balancer) the client address is in
  // X-Forwarded-For; TRUST_PROXY = number of trusted hops (unset: trust none).
  const hops = Number(process.env.TRUST_PROXY ?? 0);
  if (hops > 0) (app as NestExpressApplication).set('trust proxy', hops);
  app.use(helmet());
  app.use(cookieParser());
  app.enableCors({
    origin: config.getOrThrow<string>('WEB_ORIGIN').split(','),
    credentials: true,
    methods: ['GET', 'POST', 'PATCH', 'DELETE'],
    allowedHeaders: ['content-type', 'x-csrf-token'],
  });
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
  app.enableShutdownHooks();
  const doc = new DocumentBuilder()
    .setTitle('PulseTrader API')
    .setDescription(
      'PulseTrader V4 backend. Auth uses httpOnly cookies; writes need the x-csrf-token header.',
    )
    .setVersion('0.1.0')
    .addCookieAuth('access_token')
    .build();
  SwaggerModule.setup('api/docs', app, SwaggerModule.createDocument(app, doc));
}
