import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { APP_FILTER, APP_GUARD } from '@nestjs/core';
import { JwtModule } from '@nestjs/jwt';
import { ThrottlerGuard, ThrottlerModule } from '@nestjs/throttler';
import { AdminModule } from './admin/admin.module';
import { AlertsModule } from './alerts/alerts.module';
import { AuditModule } from './audit/audit.service';
import { AuthModule } from './auth/auth.module';
import { CsrfGuard, JwtAuthGuard } from './common/auth';
import { validateEnv } from './config/env';
import { FeaturesModule } from './features/features.module';
import { HealthModule } from './health/health.module';
import { LiveModule } from './live/live.module';
import { MarketDataModule } from './market-data/market-data.module';
import { MlModule } from './ml/ml.client';
import { ModelsModule } from './models/models.module';
import { MonitoringModule } from './monitoring/monitoring.module';
import { PortfolioModule } from './portfolio/portfolio.module';
import { PredictionsModule } from './predictions/predictions.module';
import { PrismaModule } from './prisma/prisma.module';
import { RedisModule } from './redis/redis.module';
import { ResearchModule } from './research/research.module';
import { StocksModule } from './stocks/stocks.module';
import { UsersModule } from './users/users.module';
import { WatchlistModule } from './watchlist/watchlist.module';
import { PrismaErrorsFilter } from './common/prisma-errors.filter';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, validate: validateEnv, cache: true }),
    JwtModule.registerAsync({
      global: true,
      useFactory: () => ({
        secret: process.env.JWT_SECRET,
        signOptions: { algorithm: 'HS256', issuer: 'pulsetrader-api' },
        verifyOptions: { algorithms: ['HS256'], issuer: 'pulsetrader-api' },
      }),
    }),
    ThrottlerModule.forRoot([
      { name: 'default', ttl: 60_000, limit: Number(process.env.RATE_LIMIT_PER_MINUTE ?? 120) },
    ]),
    PrismaModule,
    RedisModule,
    AuditModule,
    MlModule,
    ModelsModule,
    AuthModule,
    UsersModule,
    StocksModule,
    LiveModule,
    MonitoringModule,
    MarketDataModule,
    PredictionsModule,
    FeaturesModule,
    WatchlistModule,
    AlertsModule,
    PortfolioModule,
    ResearchModule,
    HealthModule,
    AdminModule,
  ],
  providers: [
    { provide: APP_FILTER, useClass: PrismaErrorsFilter },
    { provide: APP_GUARD, useClass: ThrottlerGuard },
    { provide: APP_GUARD, useClass: JwtAuthGuard },
    { provide: APP_GUARD, useClass: CsrfGuard },
  ],
})
export class AppModule {}
