# OpenChimera Dashboard

This is the React + TypeScript dashboard for OpenChimera.

## Features
- Session & Agent Management
- Model & Hardware Overview
- Plugin Registry
- Onboarding Wizard
- Live Logs & Diagnostics (planned)
- Settings & Auth (planned)

## Getting Started

1. Install dependencies:
   ```sh
   cd src/dashboard
   npm install
   # or
   yarn install
   ```
2. Start the dashboard:
   ```sh
   npm run dev
   # or
   yarn dev
   ```
3. Open [http://localhost:3000](http://localhost:3000) in your browser.

## Testing

- Unit tests: `npm test` or `yarn test`
- E2E tests: See `../../tests/e2e/`

## Structure
- `components/` - UI components
- `api/` - API bridge
- `onboarding/` - Onboarding wizard
- `plugins/` - Plugin registry
- `tests/` - Unit tests

---
For backend API, see the main OpenChimera Python server.
