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
    const checks = await Promise.all([
      this.checkApiKey(),
      this.checkBinary('Python', process.env.PYTHON_BIN ?? 'python', ['--version']),
      this.checkBinary('FFmpeg', 'ffmpeg', ['-version']),
      this.checkBinary('FFprobe', 'ffprobe', ['-version']),
      this.checkScript(),
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
    const local = path.resolve(__dirname, '..', '..', 'python', 'api.txt');
    if (fs.existsSync(local)) {
      return { name: 'Cle API KIE.AI', ok: true, detail: 'lue depuis api.txt (local)' };
    }
    return {
      name: 'Cle API KIE.AI',
      ok: false,
      detail: 'absente — definir KIE_API_KEY sur le serveur',
    };
  }

  private checkScript(): CheckResult {
    const script =
      process.env.PYTHON_SCRIPT_PATH ??
      path.resolve(__dirname, '..', '..', 'python', 'generate.py');
    const ok = fs.existsSync(script);
    return {
      name: 'Script de generation',
      ok,
      detail: ok ? path.basename(script) : `introuvable : ${script}`,
    };
  }

  private checkDataDir(): CheckResult {
    const dir = process.env.DATA_DIR ?? path.resolve(__dirname, '..', '..', 'data');
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.accessSync(dir, fs.constants.W_OK);
      return { name: 'Dossier de donnees', ok: true, detail: `${dir} (accessible en ecriture)` };
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
