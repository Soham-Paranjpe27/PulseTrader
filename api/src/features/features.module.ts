import { Controller, Get, Module, NotFoundException, Param } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Public } from '../common/auth';
import { MlClient } from '../ml/ml.client';
import { PrismaService } from '../prisma/prisma.service';

@ApiTags('features')
@Public()
@Controller('features')
export class FeaturesController {
  constructor(
    private readonly prisma: PrismaService,
    private readonly ml: MlClient,
  ) {}

  @Get('versions')
  versions() {
    return this.prisma.featureVersion.findMany({ orderBy: { version: 'asc' } });
  }

  @Get('versions/:version')
  async version(@Param('version') version: string) {
    const v = await this.prisma.featureVersion.findUnique({ where: { version } });
    if (!v)
      throw new NotFoundException({
        code: 'DATA_UNAVAILABLE',
        message: `unknown feature version ${version}`,
      });
    return v;
  }

  /** Live schema from the ML service: order, training statistics and missing-value rule per model. */
  @Get('schema')
  schema() {
    return this.ml.features();
  }
}

@Module({ controllers: [FeaturesController] })
export class FeaturesModule {}
