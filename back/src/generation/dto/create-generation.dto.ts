import { IsIn, IsOptional } from 'class-validator';

export class CreateGenerationDto {
  @IsOptional()
  @IsIn(['short', '60s'])
  mode: 'short' | '60s' = 'short';

  @IsOptional()
  @IsIn(['en', 'fr'])
  lang: 'en' | 'fr' = 'fr';

  @IsOptional()
  @IsIn(['runway', 'seedance'])
  videoModel: 'runway' | 'seedance' = 'runway';
}
