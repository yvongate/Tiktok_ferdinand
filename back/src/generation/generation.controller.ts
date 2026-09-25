import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  Headers,
  NotFoundException,
  Param,
  Post,
  Query,
  Res,
  Sse,
} from '@nestjs/common';
import type { Response } from 'express';
import * as fs from 'fs';
import { filter, map, merge, Observable, of } from 'rxjs';
import { CreateGenerationDto } from './dto/create-generation.dto';
import type { Job } from './job.types';
import { JobsService } from './jobs.service';

interface SseMessage {
  data: Job;
}

@Controller('generation')
export class GenerationController {
  constructor(private readonly jobs: JobsService) {}

  @Post()
  create(@Body() dto: CreateGenerationDto): Job {
    return this.jobs.create({
      mode: dto.mode ?? 'short',
      lang: dto.lang ?? 'fr',
      videoModel: dto.videoModel ?? 'runway',
    });
  }

  @Get()
  list(): Job[] {
    return this.jobs.list();
  }

  @Get(':id')
  get(@Param('id') id: string): Job {
    return this.jobs.get(id);
  }

  @Delete(':id')
  cancel(@Param('id') id: string): Job {
    return this.jobs.cancel(id);
  }

  /**
   * Suivi live d'un job (Server-Sent Events). Emet immediatement l'etat
   * courant, puis chaque mise a jour - plus simple qu'un WebSocket pour un
   * flux unidirectionnel serveur -> navigateur.
   */
  @Sse(':id/events')
  events(@Param('id') id: string): Observable<SseMessage> {
    const current = this.jobs.get(id);
    return merge(
      of(current),
      this.jobs.events.pipe(filter((job) => job.id === id)),
    ).pipe(map((job) => ({ data: job })));
  }

  /**
   * Sert la video finale, avec support des requetes Range (HTTP 206).
   * Indispensable : le <video> du navigateur demande des plages d'octets, et
   * sans reponse 206 + Content-Range il reste bloque en chargement (et on ne
   * peut pas se deplacer dans la video).
   */
  @Get(':id/video')
  video(
    @Param('id') id: string,
    @Headers('range') range: string | undefined,
    @Query('download') download: string | undefined,
    @Res() res: Response,
  ): void {
    const job = this.jobs.get(id);
    if (job.status !== 'done' || !job.videoPath) {
      throw new BadRequestException("Ce job n'a pas encore de video disponible");
    }
    if (!fs.existsSync(job.videoPath)) {
      throw new NotFoundException('Fichier video introuvable sur le disque');
    }

    const size = fs.statSync(job.videoPath).size;
    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Accept-Ranges', 'bytes');

    // Le front (Vercel) et cette API (Render) sont sur deux domaines : les
    // navigateurs IGNORENT l'attribut `download` d'un lien cross-origin. Sans
    // cet en-tete, "Telecharger" ouvrirait simplement la video dans un onglet.
    if (download !== undefined && download !== '0') {
      res.setHeader(
        'Content-Disposition',
        `attachment; filename="${this.downloadName(job)}"`,
      );
    }

    const match = range ? /bytes=(\d*)-(\d*)/.exec(range) : null;
    if (!match) {
      res.setHeader('Content-Length', size);
      fs.createReadStream(job.videoPath).pipe(res);
      return;
    }

    let start: number;
    let end: number;
    if (match[1] === '') {
      // Range suffixe "bytes=-N" = les N DERNIERS octets. Chrome s'en sert
      // pour lire l'atome moov en fin de MP4 : le confondre avec les N
      // premiers octets bloque la lecture indefiniment.
      const suffixLength = parseInt(match[2], 10);
      if (Number.isNaN(suffixLength) || suffixLength <= 0) {
        res.status(416).setHeader('Content-Range', `bytes */${size}`).end();
        return;
      }
      start = Math.max(0, size - suffixLength);
      end = size - 1;
    } else {
      start = parseInt(match[1], 10);
      end = match[2] === '' ? size - 1 : parseInt(match[2], 10);
      end = Math.min(end, size - 1); // une fin hors bornes se clampe, pas 416
    }

    if (Number.isNaN(start) || Number.isNaN(end) || start >= size || start > end) {
      res.status(416).setHeader('Content-Range', `bytes */${size}`).end();
      return;
    }

    res.status(206);
    res.setHeader('Content-Range', `bytes ${start}-${end}/${size}`);
    res.setHeader('Content-Length', end - start + 1);
    fs.createReadStream(job.videoPath, { start, end }).pipe(res);
  }

  /**
   * Nom de fichier propose au telechargement, construit depuis le titre de la
   * video. Reduit a l'ASCII sans guillemet ni saut de ligne : ce texte vient
   * d'un modele de langage et finit dans un en-tete HTTP, ou un caractere de
   * controle permettrait d'injecter d'autres en-tetes.
   */
  private downloadName(job: Job): string {
    const slug = (job.progress.idea ?? '')
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '') // enleve les accents
      .replace(/[^a-zA-Z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60)
      .toLowerCase();
    return `${slug || `ferdinand-${job.id.slice(0, 8)}`}.mp4`;
  }
}
