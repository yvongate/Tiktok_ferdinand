import { Controller, Get } from '@nestjs/common';
import { execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

export interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

export interface HealthReport {
  ok: boolean;
  checkedAt: string;
  checks: CheckResult[];
}

/**
 * Verification de l'environnement AVANT de lancer une generation.
 *
 * Une cle API absente ou un FFmpeg manquant ne se voyaient qu'apres coup, au
 * milieu d'un job — parfois apres des appels deja factures. Ce controle rend
 * ces pannes visibles tout de suite, et depuis l'interface plutot que dans les
 * logs du serveur.
 */
@Controller('health')
export class HealthController {
  @Get()
  async check(): Promise<HealthReport> {
    const python = process.env.PYTHON_BIN ?? 'python';
    const checks = await Promise.all([
      this.checkApiKey(),
      this.checkToken(),
      this.checkBinary('Python', python, ['--version']),
      this.checkBinary('FFmpeg', 'ffmpeg', ['-version']),
      this.checkBinary('FFprobe', 'ffprobe', ['-version']),
      // Pillow ne sert qu'au format graphique : sans lui, ce format echoue a
      // chaque lancement alors que tout le reste parait sain.
      this.checkBinary('Pillow (format graphique)', python, [
        '-c',
        'import PIL; print("Pillow", PIL.__version__)',
      ]),
      ...this.checkScripts(),
      this.checkPlanches(),
      this.checkDataDir(),
    ]);
    return {
      ok: checks.every((c) => c.ok),
      checkedAt: new Date().toISOString(),
      checks,
    };
  }

  private checkApiKey(): CheckResult {
    const fromEnv = process.env.KIE_API_KEY?.trim();
    if (fromEnv) {
      // On ne renvoie jamais la cle, seulement de quoi verifier que c'est la bonne.
      return { name: 'Cle API KIE.AI', ok: true, detail: `definie (…${fromEnv.slice(-4)})` };
    }
    // Memes emplacements de repli que generate.py : n'en verifier qu'un
    // affichait "cle absente" alors que le script, lui, la trouvait.
    for (const local of [
      path.resolve(__dirname, '..', '..', 'python', 'api.txt'),
      'F:\\Tiktok\\api.txt',
    ]) {
      if (fs.existsSync(local)) {
        return {
          name: 'Cle API KIE.AI',
          ok: true,
          detail: `lue depuis ${local} (local)`,
        };
      }
    }
    return {
      name: 'Cle API KIE.AI',
      ok: false,
      detail: 'absente — definir KIE_API_KEY sur le serveur',
    };
  }

  /**
   * Un controle par FORMAT. Seul generate.py etait verifie : graphique.py
   * pouvait manquer de l'image sans que rien ne l'indique, et le bandeau
   * restait vert jusqu'au premier echec.
   */
  private checkScripts(): CheckResult[] {
    const force = process.env.PYTHON_SCRIPT_PATH;
    if (force) {
      const ok = fs.existsSync(force);
      return [
        {
          name: 'Script de generation (force)',
          ok,
          detail: ok
            ? `${path.basename(force)} — PYTHON_SCRIPT_PATH impose ce script a TOUS les formats`
            : `introuvable : ${force}`,
        },
      ];
    }
    const formats: Array<[string, string]> = [
      ['Script Ferdinand', 'generate.py'],
      ['Script graphique', 'graphique.py'],
    ];
    return formats.map(([name, fichier]) => {
      const script = path.resolve(__dirname, '..', '..', 'python', fichier);
      const ok = fs.existsSync(script);
      return { name, ok, detail: ok ? fichier : `introuvable : ${script}` };
    });
  }

  /**
   * Planches de style du rendu collage.
   *
   * Sans planche, le style « vox » continue de produire une video, mais le
   * rendu derive d'une scene a l'autre et le personnage se fait remplacer -
   * mesure sur de vrais rendus. Le signaler ici evite de le decouvrir sur la
   * video finie. Non bloquant : le rendu 3D, lui, n'en a pas besoin.
   */
  private checkPlanches(): CheckResult {
    const dossier = path.resolve(__dirname, '..', '..', 'python', 'planches');
    const presentes = fs.existsSync(dossier)
      ? fs.readdirSync(dossier).filter((f) => f.endsWith('.png'))
      : [];
    return {
      name: 'Planches de style',
      ok: presentes.includes('vox.png'),
      detail: presentes.includes('vox.png')
        ? `${presentes.length} planche(s) : ${presentes.join(', ')}`
        : 'vox.png absente — le style collage rendra sans reference visuelle',
    };
  }

  /**
   * Sans jeton, l'API est ouverte : n'importe qui peut declencher des
   * generations facturees. Le signaler ici plutot que de le decouvrir sur la
   * facture.
   */
  private checkToken(): CheckResult {
    const defini = Boolean(process.env.API_TOKEN?.trim());
    if (defini) {
      return { name: "Jeton d'ecriture", ok: true, detail: 'API_TOKEN defini' };
    }
    const production = process.env.NODE_ENV === 'production';
    return {
      name: "Jeton d'ecriture",
      ok: !production,
      detail: production
        ? 'API_TOKEN absent : toutes les generations sont refusees. Definir la meme valeur ici et dans VITE_API_TOKEN cote front.'
        : 'absent — ecritures ouvertes (acceptable en local uniquement)',
    };
  }

  private checkDataDir(): CheckResult {
    const dir = process.env.DATA_DIR ?? path.resolve(__dirname, '..', '..', 'data');
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.accessSync(dir, fs.constants.W_OK);
      // La place restante manquait au tableau : le disque Render fait 5 Go et
      // une generation Ferdinand en occupe ~200 Mo avant purge. Un disque plein
      // se manifeste sinon par un echec FFmpeg incomprehensible en fin de job.
      const stat = fs.statfsSync(dir);
      const libreMo = (stat.bavail * stat.bsize) / 1048576;
      const assez = libreMo >= 500;
      return {
        name: 'Dossier de donnees',
        ok: assez,
        detail: assez
          ? `${dir} — ${libreMo.toFixed(0)} Mo libres`
          : `${dir} — seulement ${libreMo.toFixed(0)} Mo libres : supprimer des videos avant de relancer`,
      };
    } catch (err) {
      return { name: 'Dossier de donnees', ok: false, detail: (err as Error).message };
    }
  }

  private checkBinary(name: string, bin: string, args: string[]): Promise<CheckResult> {
    return new Promise((resolve) => {
      execFile(bin, args, { timeout: 5000 }, (err, stdout) => {
        if (err) {
          resolve({ name, ok: false, detail: `introuvable ou non executable (${bin})` });
          return;
        }
        resolve({ name, ok: true, detail: stdout.split('\n')[0].trim().slice(0, 80) });
      });
    });
  }
}
