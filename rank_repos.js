const { QuantumEngine } = require('./utils/quantumEngineV3.js');
const engine = new QuantumEngine();

const repos = require('./repos.js').REPOS;

// Define criteria for CHIMERA + AppForge
const criteria = [
  'Local LLM inference optimization',
  'Multi-agent orchestration', 
  'Quantum computing simulation',
  'Token compression',
  'Semantic caching',
  'Consensus voting',
  'OpenAI API compatibility',
  'RTX 2060 optimization',
  'Python implementation',
  'Production ready'
];

const options = repos.map(r => r.name + ': ' + r.desc);

// Use quantum engine to rank
(async () => {
  const result = await engine.quantumSolve(
    'Which repos are most relevant for CHIMERA (local LLM with quantum consensus) and AppForge (swarm orchestration)?',
    options,
    criteria
  );
  
  console.log('Quantum Engine Ranking:');
  console.log('=====================');
  console.log('Top 15 recommendations:');
  console.log('');
  
  // Show top results
  const allResults = [result.optimizedBest, ...result.alternatives].filter(Boolean);
  
  for (let i = 0; i < Math.min(15, allResults.length); i++) {
    const opt = allResults[i];
    const idx = options.indexOf(opt);
    if (idx >= 0) {
      console.log(`${i+1}. ${repos[idx].name}`);
      console.log(`   ${repos[idx].desc}`);
      console.log(`   ${repos[idx].stars.toLocaleString()} stars | ${repos[idx].lang} | ${repos[idx].category}`);
      console.log('');
    }
  }
  
  console.log('Confidence:', result.confidence.toFixed(2));
  console.log('Engine:', result.engineVersion);
})();
