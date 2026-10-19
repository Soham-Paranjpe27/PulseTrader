import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEmail, IsOptional, IsString, Matches, MaxLength, MinLength } from 'class-validator';

export class RegisterDto {
  @ApiProperty() @IsEmail() @MaxLength(254) email: string;

  @ApiProperty({ minLength: 12, description: 'at least 12 characters with a letter and a digit' })
  @IsString()
  @MinLength(12)
  @MaxLength(128)
  @Matches(/(?=.*[A-Za-z])(?=.*\d)/, { message: 'password needs at least one letter and one digit' })
  password: string;

  @ApiPropertyOptional() @IsOptional() @IsString() @MaxLength(100) name?: string;
}

export class LoginDto {
  @ApiProperty() @IsEmail() @MaxLength(254) email: string;
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(128) password: string;
}
