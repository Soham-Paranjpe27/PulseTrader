import { Global, Module } from '@nestjs/common';
import { ModelsController } from './models.controller';
import { ModelsService } from './models.service';

@Global()
@Module({ controllers: [ModelsController], providers: [ModelsService], exports: [ModelsService] })
export class ModelsModule {}
