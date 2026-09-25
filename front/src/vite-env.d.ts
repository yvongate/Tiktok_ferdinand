/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * URL complete du backend en production (ex. https://xxx.onrender.com).
   * Laisser vide en developpement : le proxy Vite prend le relais.
   */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
