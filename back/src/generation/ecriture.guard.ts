import {
  CanActivate,
  ExecutionContext,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import type { Request } from 'express';
import { timingSafeEqual } from 'crypto';

export const EN_TETE = 'x-ferdinand-token';

/**
 * Protege les routes qui DEPENSENT ou DETRUISENT.
 *
 * L'API etait entierement ouverte : l'adresse Render est publique, et le CORS
 * n'est qu'une politique de navigateur - un simple `curl -X POST` lancait une
 * generation Ferdinand a ~0,80 $ sur les credits du compte, ou effacait les
 * videos deja produites. Rien dans le code ne l'en empechait.
 *
 * Seules les ecritures sont filtrees. Le suivi live passe par EventSource, qui
 * ne sait PAS envoyer d'en-tete : proteger les lectures obligerait a mettre le
 * jeton dans l'URL, donc dans les journaux de tous les intermediaires. Lire un
 * avancement ne coute rien et ne detruit rien ; c'est le bon compromis.
 *
 * En production le jeton est OBLIGATOIRE : une variable oubliee laisserait le
 * trou ouvert sans que personne ne le remarque. En local il est facultatif,
 * pour ne pas imposer une configuration a chaque `npm run start:dev`.
 */
@Injectable()
export class EcritureGuard implements CanActivate {
  private readonly logger = new Logger(EcritureGuard.name);
  private static avertiUneFois = false;

  canActivate(context: ExecutionContext): boolean {
    const attendu = process.env.API_TOKEN?.trim();
    const production = process.env.NODE_ENV === 'production';

    if (!attendu) {
      if (production) {
        this.logger.error(
          'API_TOKEN absent en production : toutes les ecritures sont refusees.',
        );
        throw new UnauthorizedException(
          "API_TOKEN n'est pas defini sur le serveur : les generations sont bloquees " +
            'tant que ce jeton manque (sinon l\'API serait ouverte a tous).',
        );
      }
      if (!EcritureGuard.avertiUneFois) {
        EcritureGuard.avertiUneFois = true;
        this.logger.warn(
          'API_TOKEN absent : ecritures ouvertes (tolere hors production uniquement).',
        );
      }
      return true;
    }

    const req = context.switchToHttp().getRequest<Request>();
    const recu = req.header(EN_TETE)?.trim() ?? '';
    if (!EcritureGuard.egales(recu, attendu)) {
      throw new UnauthorizedException('Jeton absent ou invalide.');
    }
    return true;
  }

  /** Comparaison a duree constante : une comparaison naive de chaines laisse
   *  fuir la longueur du jeton et ses premiers caracteres. */
  private static egales(a: string, b: string): boolean {
    const ba = Buffer.from(a, 'utf8');
    const bb = Buffer.from(b, 'utf8');
    if (ba.length !== bb.length) return false;
    return timingSafeEqual(ba, bb);
  }
}
