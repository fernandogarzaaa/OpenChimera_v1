import { conditionalOptimize } from './token_optimizer';

export class SwarmController {
    private agents: string[] = [];
    private contextPayload: string = "";

    constructor() {}

    /**
     * Add context to the swarm controller payload.
     * Automatically triggers the 98% Token Optimizer if context grows too large.
     */
    addContext(newData: string) {
        this.contextPayload += "\n" + newData;
        // Hook in the token optimizer with a 10KB threshold (for example)
        this.contextPayload = conditionalOptimize(this.contextPayload, 10000);
    }

    addAgent(agentId: string) {
        this.agents.push(agentId);
        console.log(`Agent ${agentId} joined the swarm.`);
    }

    executeTask(task: string) {
        console.log(`[SwarmController] Executing task with ${this.agents.length} agents.`);
        console.log(`[SwarmController] Context payload size: ${this.contextPayload.length}`);
        
        // Pass the optimized context to agents (simulated)
        for (const agent of this.agents) {
            console.log(`Agent ${agent} executing task with optimized context.`);
        }
    }
}
