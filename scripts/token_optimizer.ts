/**
 * 98% Token Optimizer Concept in TypeScript
 * Aggressively reduces text size by removing comments, blank lines,
 * and collapsing whitespace to retain bare-metal logic and architectural nodes.
 */
export function optimizeTokens(context: string): string {
    if (!context) return context;

    let optimized = context;

    // Remove single-line comments
    optimized = optimized.replace(/\/\/[^\n]*\n/g, '\n');
    
    // Remove multi-line comments
    optimized = optimized.replace(/\/\*[\s\S]*?\*\//g, '');
    
    // Remove docstrings / triple quotes if it resembles python
    optimized = optimized.replace(/'''[\s\S]*?'''/g, '');
    optimized = optimized.replace(/"""[\s\S]*?"""/g, '');

    // Collapse multiple spaces to single space
    optimized = optimized.replace(/ {2,}/g, ' ');

    // Collapse multiple newlines
    optimized = optimized.replace(/\n\s*\n/g, '\n');

    // Remove leading/trailing whitespace
    optimized = optimized.trim();

    return optimized;
}

/**
 * Checks if the context payload exceeds the threshold and compresses it if so.
 */
export function conditionalOptimize(context: string, maxBytes: number = 50000): string {
    if (context.length > maxBytes) {
        console.log(`[Token Optimizer] Compressing context payload (original length: ${context.length} chars)`);
        const result = optimizeTokens(context);
        console.log(`[Token Optimizer] Compression complete (new length: ${result.length} chars)`);
        return result;
    }
    return context;
}
