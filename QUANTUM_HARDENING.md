# QUANTUM DIRECTIVE: Dependency Hardening & Auth Audit

## Objective
1. **Dependency Hardening**: Resolve the 45 vulnerabilities in `package.json` by updating `devDependencies` and refactoring non-critical packages.
2. **Auth Verification**: Execute the Playwright test suite specifically targeting authentication and security headers.

## Swarm Assignments
1. **Hardening Swarm (`dependency-hardener`)**:
   - Navigate to `D:\appforge-main\appforge`.
   - Analyze the `package.json` audit warnings.
   - Refactor/Update `devDependencies` to modern versions that clear the 45 vulnerabilities.
   - Update `package.json` and run `npm install`.

2. **Auth Verification Swarm (`playwright-auth-auditor`)**:
   - Navigate to `D:\appforge-main\appforge`.
   - Run the playwright test suite focusing on e2e authentication: `npx playwright test -c e2e/playwright.config.js`.
   - Ensure auth flows are bug-proof.
