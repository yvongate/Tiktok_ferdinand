import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';

export interface Idea {
  /** Numero d'ordre dans la liste validee (1-based). */
  n: number;
  cat: string;
  /** Titre francais - sert uniquement a la relecture humaine. */
  fr: string;
  /** Titre allemand - c'est CELUI-CI qui part en production. */
  de: string;
}

export interface IdeasProgress {
  total: number;
  used: number;
  remaining: number;
  percent: number;
  /** Prochaine idee qui sera consommee, ou null si la liste est epuisee. */
  next: Idea | null;
}

/**
 * File d'idees validees a la main, consommee sequentiellement.
 *
 * La LISTE est versionnee avec le code (ideas_de.json) : c'est un contenu
 * relu et approuve, pas une donnee generee. Le CURSEUR, lui, vit dans
 * DATA_DIR, donc sur le disque persistant de Render - sinon chaque
 * redeploiement remettrait le compteur a zero et regenererait des videos
 * deja publiees.
 */
@Injectable()
export class IdeasService implements OnModuleInit {
  private readonly logger = new Logger(IdeasService.name);
  private ideas: Idea[] = [];
  private consumed = new Set<number>();

  private get dataDir(): string {
    return process.env.DATA_DIR ?? path.resolve(__dirname, '..', '..', 'data');
  }

  private get stateFile(): string {
    return path.join(this.dataDir, 'ideas-state.json');
  }

  private get listFile(): string {
    return (
      process.env.IDEAS_FILE ??
      path.resolve(__dirname, '..', '..', 'python', 'ideas_de.json')
    );
  }

  onModuleInit() {
    this.loadList();
    this.loadState();
  }

  private loadList() {
    try {
      const raw = fs.readFileSync(this.listFile, 'utf8');
      this.ideas = (JSON.parse(raw) as Idea[]).filter((i) => i?.de?.trim());
      this.logger.log(`${this.ideas.length} idees chargees depuis ${this.listFile}`);
    } catch (err) {
      // Non bloquant : sans liste, le pipeline retombe sur la generation
      // d'idees par le modele, comme avant.
      this.ideas = [];
      this.logger.warn(`Liste d'idees illisible : ${(err as Error).message}`);
    }
  }

  private loadState() {
    try {
      if (!fs.existsSync(this.stateFile)) return;
      const saved = JSON.parse(fs.readFileSync(this.stateFile, 'utf8')) as {
        consumed?: number[];
      };
      this.consumed = new Set(saved.consumed ?? []);
      this.logger.log(`${this.consumed.size} idee(s) deja consommee(s)`);
    } catch (err) {
      this.logger.warn(`Etat des idees illisible : ${(err as Error).message}`);
    }
  }

  private saveState() {
    try {
      fs.mkdirSync(this.dataDir, { recursive: true });
      fs.writeFileSync(
        this.stateFile,
        JSON.stringify({ consumed: [...this.consumed].sort((a, b) => a - b) }, null, 2),
        'utf8',
      );
    } catch (err) {
      this.logger.warn(`Etat des idees non sauvegarde : ${(err as Error).message}`);
    }
  }

  /** Prochaine idee non consommee, sans la reserver. */
  peek(): Idea | null {
    return this.ideas.find((i) => !this.consumed.has(i.n)) ?? null;
  }

  /**
   * Marque une idee comme consommee. Appele a la REUSSITE du job, jamais au
   * lancement : un job echoue ou annule doit pouvoir etre relance sur la meme
   * idee plutot que de la bruler.
   */
  markUsed(n: number) {
    if (this.consumed.has(n)) return;
    this.consumed.add(n);
    this.saveState();
    this.logger.log(`Idee ${n} consommee (${this.consumed.size}/${this.ideas.length})`);
  }

  progress(): IdeasProgress {
    const total = this.ideas.length;
    const used = this.consumed.size;
    return {
      total,
      used,
      remaining: total - used,
      percent: total > 0 ? Math.round((used / total) * 100) : 0,
      next: this.peek(),
    };
  }

  /** Vrai quand aucune liste n'est chargee : on laisse alors le modele improviser. */
  get isEmpty(): boolean {
    return this.ideas.length === 0;
  }
}
