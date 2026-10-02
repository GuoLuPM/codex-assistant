import {defineConfig} from '@playwright/test';
const python=process.env.ASSISTANT_TEST_PYTHON??'python';
const port=process.env.ASSISTANT_TEST_PORT??'51937';
export default defineConfig({
  outputDir:'../../data/browser-checks/results',
  testDir:'tests',testMatch:'*.spec.ts',workers:1,timeout:45000,
  use:{baseURL:`http://127.0.0.1:${port}`,browserName:'chromium',channel:process.env.CI?undefined:'msedge',headless:true},
  webServer:{command:`"${python}" ../tests/browser_server.py`,url:`http://127.0.0.1:${port}/`,reuseExistingServer:false,timeout:30000},
});
