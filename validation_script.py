import asyncio
from swarm_v2 import SwarmOrchestrator, ProcessMode
import json
import token_fracture 

TASK = 'Final Architectural Validation via Subagent'

async def spec_handler(task, context, prev):
    long_output = f'This is the initial analysis task output for {task}. It contains a lot of descriptive context that should be heavily pruned before moving to the next step for token efficiency.' * 3
    return {'context_set_by_spec': long_output}

async def build_handler(task, context, prev):
    prev_output = context.get('compressed_output', 'FAIL: Context missing')
    return f'Build: Context received: {prev_output}'

async def test_handler(task, context, prev):
    prev_compressed = context.get('compressed_output', 'FAIL: Compressed Context missing')
    return f'Test: Final check. Received context (first 100 chars): {prev_compressed[:100]}...'
            
async def main():
    orchestrator = SwarmOrchestrator('compression-validation-swarm', ProcessMode.SEQUENTIAL)
    
    orchestrator.register_agent('spec', 'Spec Agent', spec_handler)
    orchestrator.register_agent('build', 'Builder Agent', build_handler)
    orchestrator.register_agent('test', 'Test Agent', test_handler)
        
    orchestrator.set_handoff('spec', 'build')
    orchestrator.set_handoff('build', 'test')
    
    print('--- Starting Final Token Optimization Flow Validation via Subagent ---')
    results = await orchestrator.execute_task(TASK, context={'initial_seed': True})
    
    print('\\n--- Final Validation Results ---')
    print(json.dumps(results, indent=2))

asyncio.run(main())