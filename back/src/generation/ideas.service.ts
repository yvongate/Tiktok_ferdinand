import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';

/** Les deux formats produits, chacun avec sa liste validee. */
export type Format = 'ferdinand' | 'graphique';

export const FORMATS: Format[] = ['ferdinand', 'graphique'];

export interface Idea {
  /** Numero d'ordre dans la liste validee (1-based). */
  n: number;
  // --- format ferdinand ---
  cat?: string;
  /** Titre francais : relecture humaine uniquement. */
  fr?: string;
  /** Titre allemand : c'est CELUI-CI qui part en production. */
  de?: string;
  // --- format graphique ---
  nom?: string;
  symbole?: string;
  annees?: number;
  histoire?: string;
  sommet?: number;
  final?: number;
}

/** Libelle affichable d'une entree, quel que soit le format. */
export function titreIdee(idea: Idea): string {
  return idea.de ?? `${idea.nom} — ${idea.annees} ans`;
}

interface Config {
  liste: string;
  etat: string;
}

const LISTES: Record<Format, Config> = {
  ferdinand: { liste: 'ideas_de.json', etat: 'ideas-state.json' },
  graphique: { liste: 'subjects_de.json', etat: 'subjects-state.json' },
};

export interface IdeasProgress {
  format: Format;
  total: number;
  used: number;
  remaining: number;
  percent: number;
  /** Prochaine entree qui sera consommee, ou null si la liste est epuisee. */
  next: Idea | null;
}

/**
 * Listes validees a la main, consommees sequentiellement.
 *
 * Les LISTES sont versionnees avec le code : c'est du contenu relu et
 * approuve, pas une donnee generee. Les CURSEURS vivent dans DATA_DIR, donc
 * sur le disque persistant - sinon chaque redeploiement remettrait les
 * compteurs a zero et regenererait des videos deja publiees.
 *
 * Un curseur par format : consommer une idee Ferdinand ne doit pas faire
 * avancer les sujets graphiques.
 */
@Injectable()
export class IdeasService implements OnModuleInit {
  private readonly logger = new Logger(IdeasService.name);
  private readonly listes = new Map<Format, Idea[]>();
  private readonly consommees = new Map<Format, Set<number>>();

  private get dataDir(): string {
    return process.env.DATA_DIR ?? path.resolve(__dirname, '..', '..', 'data');
  }

  private get pythonDir(): string {
    return path.resolve(__dirname, '..', '..', 'python');
  }

  onModuleInit() {
    for (const format of FORMATS) {
      this.charger(format);
      this.relireEtat(format);
    }
  }

  private charger(format: Format) {
    const fichier = path.join(this.pythonDir, LISTES[format].liste);
    try {
      const brut = JSON.parse(fs.readFileSync(fichier, 'utf8')) as Idea[];
      const valides = brut.filter((i) => i?.de?.trim() || i?.symbole?.trim());
      this.listes.set(format, valides);
      this.logger.log(`${format} : ${valides.length} entrees chargees`);
    } catch (err) {
      // Non bloquant : sans liste, le pipeline Ferdinand retombe sur la
      // generation d'idees par le modele, comme avant.
      this.listes.set(format, []);
      this.logger.warn(`${format} : liste illisible (${(err as Error).message})`);
    }
  }

  private relireEtat(format: Format) {
    const fichier = path.join(this.dataDir, LISTES[format].etat);
    this.consommees.set(format, new Set());
    try {
      if (!fs.existsSync(fichier)) return;
      const saved = JSON.parse(fs.readFileSync(fichier, 'utf8')) as { consumed?: number[] };
      this.consommees.set(format, new Set(saved.consumed ?? []));
      this.logger.log(`${format} : ${saved.consumed?.length ?? 0} deja consommee(s)`);
    } catch (err) {
      this.logger.warn(`${format} : etat illisible (${(err as Error).message})`);
    }
  }

  private sauver(format: Format) {
    try {
      fs.mkdirSync(this.dataDir, { recursive: true });
      const liste = [...(this.consommees.get(format) ?? [])].sort((a, b) => a - b);
      fs.writeFileSync(
        path.join(this.dataDir, LISTES[format].etat),
        JSON.stringify({ consumed: liste }, null, 2),
        'utf8',
      );
    } catch (err) {
      this.logger.warn(`${format} : etat non sauvegarde (${(err as Error).message})`);
    }
  }

  /** Prochaine entree non consommee, sans la reserver. */
  peek(format: Format): Idea | null {
    const consommees = this.consommees.get(format) ?? new Set<number>();
    return (this.listes.get(format) ?? []).find((i) => !consommees.has(i.n)) ?? null;
  }

  /**
   * Marque une entree consommee. Appele a la REUSSITE du job, jamais au
   * lancement : un job echoue ou annule doit pouvoir etre relance sur le
   * meme sujet plutot que de le bruler.
   */
  markUsed(format: Format, n: number) {
    const set = this.consommees.get(format);
    if (!set || set.has(n)) return;
    set.add(n);
    this.sauver(format);
    this.logger.log(
      `${format} : entree ${n} consommee (${set.size}/${this.listes.get(format)?.length ?? 0})`,
    );
  }

  progress(format: Format): IdeasProgress {
    const total = this.listes.get(format)?.length ?? 0;
    const used = this.consommees.get(format)?.size ?? 0;
    return {
      format,
      total,
      used,
      remaining: total - used,
      percent: total > 0 ? Math.round((used / total) * 100) : 0,
      next: this.peek(format),
    };
  }

  tousLesProgres(): IdeasProgress[] {
    return FORMATS.map((f) => this.progress(f));
  }

  /** Vrai quand aucune liste n'est chargee pour ce format. */
  isEmpty(format: Format): boolean {
    return (this.listes.get(format)?.length ?? 0) === 0;
  }
}
