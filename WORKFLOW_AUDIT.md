# GitHub Actions Workflow Audit

## 1. Overview
This document contains an audit of the GitHub Actions workflows located in `.github/workflows/`. Currently, there is only one workflow file: `deploy.yml`. 

## 2. Findings and Critical Issues

### A. Critical: PRs Deploying to Production (Environment Leakage)
- **Issue**: The `deploy.yml` workflow triggers on both `push` to `main` and `pull_request`. However, the build and deploy steps explicitly use the `--prod` flag (`vercel build --prod` and `vercel deploy --prod`). 
- **Impact**: Every pull request opened against the repository will overwrite the production environment, causing massive instability and exposing untested code to end users.

### B. Missing Concurrency Controls (Race Conditions)
- **Issue**: There is no `concurrency` block defined.
- **Impact**: If multiple commits are pushed rapidly to `main` or a PR is updated multiple times quickly, multiple concurrent jobs will run. This leads to race conditions where an older commit might finish deploying *after* a newer commit, leaving the production site in a stale state. It also wastes GitHub Actions minutes and Vercel build slots.

### C. Missing Caching Layers (Wasted Compute/Time)
- **Issue**: The step `npm install --global vercel@latest` installs the Vercel CLI from scratch on every run.
- **Impact**: Unnecessary network overhead and delayed deployment times. There is no `actions/setup-node` usage or global `npm` cache preservation.

### D. Fragile Health Check Mechanics
- **Issue**: A hardcoded `sleep 10` is used before running a health check probe.
- **Impact**: Deployment times vary. 10 seconds might be too long (wasting time) or too short (causing the health check to fail unnecessarily before Vercel finishes routing). While `curl` has retries, the hardcoded sleep is an anti-pattern.

## 3. Concrete Optimization Plan

### Step 1: Split Environments (Production vs. Preview)
Modify the script to detect the event type and branch, passing the correct flags to Vercel.
- On `push` to `main`: Use `--prod`.
- On `pull_request`: Omit `--prod` to create a preview deployment.

### Step 2: Implement Concurrency Groups
Add a concurrency block to cancel in-progress runs for the same branch/PR.
```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

### Step 3: Implement Caching for Node/NPM
Add the `actions/setup-node` action to leverage caching for the Vercel CLI.
```yaml
- name: Setup Node
  uses: actions/setup-node@v4
  with:
    node-version: '20'
    cache: 'npm'
```
*Alternatively, consider migrating to the official or community Vercel GitHub Actions (e.g., `amondnet/vercel-action`) which abstract away CLI installation and caching.*

### Step 4: Optimize Health Checks
Remove the `sleep 10` step. Rely entirely on the `curl` retry mechanism, but increase the retry count or delay if necessary to account for Vercel's edge network propagation.

## 4. Proposed `deploy.yml` Structure

```yaml
name: Deploy to Vercel

on:
  push:
    branches:
      - main
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Cache Node Modules
        uses: actions/cache@v3
        with:
          path: ~/.npm
          key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
          restore-keys: |
            ${{ runner.os }}-node-

      - name: Install Vercel CLI
        run: npm install --global vercel@latest

      - name: Pull Vercel Environment Information
        run: vercel pull --yes --environment=${{ github.ref == 'refs/heads/main' && 'production' || 'preview' }} --token=${{ secrets.VERCEL_TOKEN }}
        env:
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}

      - name: Build Project Artifacts
        run: vercel build ${{ github.ref == 'refs/heads/main' && '--prod' || '' }} --token=${{ secrets.VERCEL_TOKEN }}
        env:
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}

      - name: Deploy Project Artifacts to Vercel
        id: deploy
        run: |
          DEPLOY_URL=$(vercel deploy --prebuilt ${{ github.ref == 'refs/heads/main' && '--prod' || '' }} --token=${{ secrets.VERCEL_TOKEN }})
          echo "url=$DEPLOY_URL" >> $GITHUB_OUTPUT
          echo "Deployed to $DEPLOY_URL"
        env:
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}

      - name: Health Check Probe
        run: |
          echo "Checking health of ${{ steps.deploy.outputs.url }}..."
          curl --fail --silent --show-error --max-time 10 --retry 10 --retry-connrefused --retry-delay 5 "${{ steps.deploy.outputs.url }}"
          echo "Health check passed."
```