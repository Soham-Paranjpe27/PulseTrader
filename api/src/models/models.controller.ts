import { Controller, Get, NotFoundException, Param } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Public } from '../common/auth';
import { PrismaService } from '../prisma/prisma.service';
import { ModelsService } from './models.service';

@ApiTags('models')
@Public()
@Controller('models')
export class ModelsController {
  constructor(
    private readonly models: ModelsService,
    private readonly prisma: PrismaService,
  ) {}

  @Get()
  list() {
    return this.models.list();
  }

  @Get('active')
  active() {
    return this.models.active();
  }

  @Get(':id')
  async get(@Param('id') id: string) {
    const m = await this.prisma.modelVersion.findUnique({ where: { id } });
    if (!m) throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `unknown model ${id}` });
    return m;
  }
}
