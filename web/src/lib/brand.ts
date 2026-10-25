/** The product name in one place. Set VITE_APP_NAME at build time to rename the app everywhere it is shown. */
export const BRAND: string = (import.meta.env.VITE_APP_NAME as string | undefined) || 'HootRoute';
