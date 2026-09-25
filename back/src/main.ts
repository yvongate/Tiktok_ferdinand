import { ValidationPipe } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

/**
 * Origines autorisees. FRONT_ORIGIN accepte plusieurs valeurs separees par des
 * virgules : Vercel sert le site de production sur un domaine, mais chaque
 * deploiement de preversion sur un domaine different. Sans cette liste, seule
 * la production fonctionnerait et toute preversion serait bloquee par le
 * navigateur, sans message explicite cote interface.
 */
function corsOrigins(): string[] {
  const raw = process.env.FRONT_ORIGIN ?? 'http://localhost:5173';
  return raw
    .split(',')
    .map((o) => o.trim().replace(/\/+$/, ''))
    .filter(Boolean);
}

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.setGlobalPrefix('api');

  const origins = corsOrigins();
  app.enableCors({
    origin: origins.includes('*') ? true : origins,
    // Le suivi live passe par EventSource : la reponse doit rester en flux,
    // et la requete de controle prealable doit accepter GET.
    methods: ['GET', 'POST', 'DELETE', 'OPTIONS'],
  });

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true, // ignore les champs non declares dans le DTO
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );

  // Render fournit le port a ecouter et exige une ecoute sur 0.0.0.0 :
  // par defaut Nest n'ecoute que sur localhost, et le service serait
  // considere comme mort au demarrage.
  await app.listen(process.env.PORT ?? 3000, '0.0.0.0');
}
bootstrap();
