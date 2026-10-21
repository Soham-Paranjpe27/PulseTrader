import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import {
  ArrayMaxSize,
  ArrayMinSize,
  IsInt,
  IsISO8601,
  IsOptional,
  IsString,
  Matches,
  MaxLength,
  Min,
  ValidateNested,
} from 'class-validator';
import { SYMBOL_RE } from '../common/pagination';

export class CreatePredictionDto {
  @ApiProperty({ example: 'RELIANCE' }) @IsString() @Matches(SYMBOL_RE) symbol: string;

  @ApiProperty({
    example: '2025-01-06T10:30:00+05:30',
    description: 'bar start of the latest closed 1-minute bar',
  })
  @IsISO8601({ strict: true })
  @Matches(/(Z|[+-]\d{2}:\d{2})$/, { message: 'timestamp must include a timezone' })
  timestamp: string;

  @ApiPropertyOptional({ example: 'lightgbm-y_5m_10bp-tuned' })
  @IsOptional()
  @IsString()
  @MaxLength(100)
  modelId?: string;
  @ApiPropertyOptional() @IsOptional() @Type(() => Number) @IsInt() @Min(1) modelVersion?: number;
  @ApiPropertyOptional() @IsOptional() @IsString() @MaxLength(40) task?: string;
}

export class BatchPredictionDto {
  @ApiProperty({ type: [CreatePredictionDto] })
  @ValidateNested({ each: true })
  @Type(() => CreatePredictionDto)
  @ArrayMinSize(1)
  @ArrayMaxSize(200)
  items: CreatePredictionDto[];
}
