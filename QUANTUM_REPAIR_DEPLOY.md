# QUANTUM DIRECTIVE: Integration Repair Deployment

## Objective
Repair the integration gaps identified by the E2E audit. 
- Ensure the backend server is running in the correct directory.
- Map the frontend UI components to the real backend data.

## Swarm Assignments
1. **Backend Connectivity Swarm (`backend-fixer-swarm`)**:
   - Location: `D:\appforge-main\appforge\backend`.
   - Goal: Ensure `server.js` is running reliably. Use `pm2` or `node server.js` and verify with `Get-NetTCPConnection` that port 5000 (or the required port) is open.
   
2. **Frontend UI/Navigation Swarm (`ui-fixer-swarm`)**:
   - Location: `D:\appforge-main\appforge\src\components`.
   - Goal: Map the navigation and health status components to the actual JSON-RPC responses from `localhost:8000/mcp` and the API server. Fix the `toBeVisible` failures in Playwright tests.
