// tests/e2e/dashboard.spec.ts
import { test, expect } from '@playwright/test';

test.describe('OpenChimera Dashboard', () => {
  test('loads dashboard main page', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await expect(page.locator('header')).toContainText('OpenChimera Dashboard');
  });

  test('shows onboarding wizard', async ({ page }) => {
    await page.goto('http://localhost:3000/onboarding');
    await expect(page.locator('h2')).toContainText('Welcome');
  });

  test('lists sessions', async ({ page }) => {
    await page.goto('http://localhost:3000/dashboard');
    await expect(page.locator('h2')).toContainText('Sessions');
  });

  test('shows plugin registry', async ({ page }) => {
    await page.goto('http://localhost:3000/plugins');
    await expect(page.locator('h2')).toContainText('Plugin Registry');
  });
});
