import { IsIn, IsOptional } from 'class-validator';

export class CreateGenerationDto {
  @IsOptional()
  @IsIn(['ferdinand', 'graphique'])
  format: 'ferdinand' | 'graphique' = 'ferdinand';

  @IsOptional()
  @IsIn(['short', '60s'])
  mode: 'short' | '60s' = 'short';

  @IsOptional()
  @IsIn(['en', 'fr', 'de'])
  // Allemand par defaut : la chaine cible le marche allemand.
  lang: 'en' | 'fr' | 'de' = 'de';

  @IsOptional()
  @IsIn(['runway', 'seedance'])
  videoModel: 'runway' | 'seedance' = 'runway';

  @IsOptional()
  @IsIn(['ferdinand', 'vox'])
  style: 'ferdinand' | 'vox' = 'ferdinand';

  @IsOptional()
  @IsIn(['720p', '1080p'])
  quality: '720p' | '1080p' = '720p';
}
