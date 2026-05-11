/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly PROD: boolean;
  readonly VITE_APP_ORIGIN?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_WS_BASE_URL?: string;
  readonly VITE_GATEWAY_WS_BASE_URL?: string;
  readonly VITE_LIVEKIT_WS_URL?: string;
  readonly VITE_PUBLIC_APP_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "animejs" {
  const anime: any;
  export default anime;
}
