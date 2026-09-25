import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { GenerationModule } from './generation/generation.module';

@Module({
  imports: [GenerationModule],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
