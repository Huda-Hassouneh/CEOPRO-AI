import { CompetitorError } from '../types/competitors.types.js';

// The team's standalone Python workers do not implement the withdrawn Node
// event/lease/preview contract. Environment variables cannot re-enable it.
export const COMPETITOR_AI_ACTIONS_ENABLED = false;

export function requireCompetitorAiActions(): void {
  if (!COMPETITOR_AI_ACTIONS_ENABLED) {
    throw new CompetitorError('NOT_IMPLEMENTED', {
      reason: 'COMPETITOR_WORKER_CONTRACT_NOT_CONNECTED'
    });
  }
}
