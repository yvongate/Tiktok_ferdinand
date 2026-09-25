import { Module } from '@nestjs/common';
import { GenerationController } from './generation.controller';
import { HealthController } from './health.controller';
import { JobsService } from './jobs.service';
import { PythonRunnerService } from './python-runner.service';

@Module({
  controllers: [GenerationController, HealthController],
  providers: [JobsService, PythonRunnerService],
})
export class GenerationModule {}
