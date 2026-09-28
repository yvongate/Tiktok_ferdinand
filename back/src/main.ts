import { Logger, ValidationPipe } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { EN_TETE } from './generation/ecriture.guard';

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
    // Sans declarer l'en-tete de jeton ici, le navigateur bloque la requete de
    // controle prealable et aucune generation ne peut plus partir du site.
    allowedHeaders: ['Content-Type', EN_TETE],
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
  // Avertissement au demarrage plutot qu'au premier abus : sans jeton, un
  // inconnu peut declencher des generations facturees sur ce compte.
  if (!process.env.API_TOKEN?.trim()) {
    new Logger('Securite').warn(
      process.env.NODE_ENV === 'production'
        ? 'API_TOKEN absent : toutes les generations seront refusees.'
        : 'API_TOKEN absent : ecritures non protegees (acceptable en local).',
    );
  }

  await app.listen(process.env.PORT ?? 3000, '0.0.0.0');
}
bootstrap();
