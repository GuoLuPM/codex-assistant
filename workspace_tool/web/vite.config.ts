import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()], build:{target:'es2022'}, test:{environment:'jsdom',include:['tests/**/*.test.ts','tests/**/*.test.tsx'],setupFiles:['tests/setup.ts']}});
