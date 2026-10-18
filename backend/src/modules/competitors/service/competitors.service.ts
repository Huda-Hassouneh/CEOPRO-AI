import { competitorsRepo } from '../repo/competitors.repo.js';
import { requireCompetitorAiActions } from './competitor-capabilities.js';

function workerOnly<T extends (...args: any[]) => any>(operation: T): T {
  return ((...args: Parameters<T>) => {
    requireCompetitorAiActions();
    return operation(...args);
  }) as T;
}

// Directory reads and alias editing remain independent of the worker bridge.
export const competitorsService = {
  ...competitorsRepo,
  create: workerOnly(competitorsRepo.create),
  track: workerOnly(competitorsRepo.track),
  discover: workerOnly(competitorsRepo.discover),
  cancelDiscovery: workerOnly(competitorsRepo.cancelDiscovery),
  schedule: workerOnly(competitorsRepo.schedule),
  confirm: workerOnly(competitorsRepo.confirm),
  reviewSource: workerOnly(competitorsRepo.reviewSource),
  retryCollection: workerOnly(competitorsRepo.retryCollection),
  linkProduct: workerOnly(competitorsRepo.linkProduct),
  previewProduct: workerOnly(competitorsRepo.previewProduct),
  rejectCandidate: workerOnly(competitorsRepo.rejectCandidate),
  catalogProducts: workerOnly(competitorsRepo.catalogProducts),
  productCandidates: workerOnly(competitorsRepo.productCandidates)
};
