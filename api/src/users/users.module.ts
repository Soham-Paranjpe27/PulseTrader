import { Body, Controller, Get, Module, Patch, Query } from '@nestjs/common';
import { ApiPropertyOptional, ApiTags } from '@nestjs/swagger';
import { Role } from '@prisma/client';
import { IsOptional, IsString, MaxLength } from 'class-validator';
import { publicUser } from '../auth/auth.service';
import { AuthUser, CurrentUser, Roles } from '../common/auth';
import { PageQuery } from '../common/pagination';
import { PrismaService } from '../prisma/prisma.service';

class UpdateMeDto {
  @ApiPropertyOptional() @IsOptional() @IsString() @MaxLength(100) name?: string;
}

@ApiTags('users')
@Controller('users')
export class UsersController {
  constructor(private readonly prisma: PrismaService) {}

  @Get('me')
  async me(@CurrentUser() u: AuthUser) {
    return publicUser(await this.prisma.user.findUniqueOrThrow({ where: { id: u.id } }));
  }

  @Patch('me')
  async update(@CurrentUser() u: AuthUser, @Body() dto: UpdateMeDto) {
    return publicUser(await this.prisma.user.update({ where: { id: u.id }, data: { name: dto.name } }));
  }

  @Roles(Role.ADMIN)
  @Get()
  async list(@Query() q: PageQuery) {
    const rows = await this.prisma.user.findMany({
      orderBy: { createdAt: 'asc' },
      skip: (q.page - 1) * q.pageSize,
      take: q.pageSize,
    });
    return { items: rows.map(publicUser), total: await this.prisma.user.count() };
  }
}

@Module({ controllers: [UsersController] })
export class UsersModule {}
