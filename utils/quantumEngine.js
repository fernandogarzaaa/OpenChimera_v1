/**
 * Clawd's Quantum Engine Wrapper
 * Integrates Inan's Quantum Engine V3.0
 */

import QuantumEngine from './quantumEngineV3.js';

// Create singleton instance
const quantumEngine = new QuantumEngine();

export default quantumEngine;

// Re-export for compatibility
export { quantumEngine };

// Log status
console.log('⚡ Quantum Engine V3.0 integrated:', quantumEngine.getStats());
