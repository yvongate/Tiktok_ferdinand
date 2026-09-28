/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * URL complete du backend en production (ex. https://xxx.onrender.com).
   * Laisser vide en developpement : le proxy Vite prend le relais.
   */
  readonly VITE_API_BASE?: string
  /**
   * Jeton d'ecriture, identique a API_TOKEN cote backend. Sans lui, les
   * lancements et suppressions sont refuses en production. Il est fige dans le
   * bundle a la compilation : changer sa valeur demande un redeploiement du
   * front ET du back.
   */
  readonly VITE_API_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
