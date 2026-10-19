import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';
import { Observable, Subject } from 'rxjs';

/**
 * Redis for caching and pub/sub of new predictions (fan-out to SSE clients across API instances).
 * Redis being down never breaks a request: cache misses fall through to the source, and the failure
 * is logged and visible in /api/health/ready.
 */
@Injectable()
export class RedisService implements OnModuleDestroy {
  private readonly log = new Logger(RedisService.name);
  readonly client: Redis;
  private readonly sub: Redis;
  private readonly events = new Subject<{ channel: string; message: string }>();

  constructor(config: ConfigService) {
    const url = config.getOrThrow<string>('REDIS_URL');
    const opts = { lazyConnect: true, maxRetriesPerRequest: 1, enableOfflineQueue: false };
    this.client = new Redis(url, opts);
    this.sub = new Redis(url, opts);
    for (const c of [this.client, this.sub]) {
      c.on('error', (e: Error) => this.log.warn(`redis: ${e.message}`));
    }
    this.sub.on('message', (channel: string, message: string) => this.events.next({ channel, message }));
    void this.connect();
  }

  private async connect(): Promise<void> {
    try {
      await this.client.connect();
      await this.sub.connect();
      await this.sub.subscribe('predictions');
    } catch (e) {
      this.log.warn(`redis unavailable: ${(e as Error).message}`);
    }
  }

  async ping(): Promise<boolean> {
    try {
      return (await this.client.ping()) === 'PONG';
    } catch (e) {
      this.log.warn(`redis ping failed: ${(e as Error).message}`);
      return false;
    }
  }

  async getJson<T>(key: string): Promise<T | null> {
    try {
      const v = await this.client.get(key);
      return v ? (JSON.parse(v) as T) : null;
    } catch (e) {
      this.log.warn(`redis get ${key} failed: ${(e as Error).message}`);
      return null;
    }
  }

  async setJson(key: string, value: unknown, ttlSeconds: number): Promise<void> {
    try {
      await this.client.set(key, JSON.stringify(value), 'EX', ttlSeconds);
    } catch (e) {
      this.log.warn(`redis set ${key} failed: ${(e as Error).message}`);
    }
  }

  async publish(channel: string, message: unknown): Promise<boolean> {
    try {
      await this.client.publish(channel, JSON.stringify(message));
      return true;
    } catch (e) {
      this.log.warn(`redis publish failed: ${(e as Error).message}`);
      return false;
    }
  }

  stream(): Observable<{ channel: string; message: string }> {
    return this.events.asObservable();
  }

  async onModuleDestroy(): Promise<void> {
    this.client.disconnect();
    this.sub.disconnect();
  }
}
