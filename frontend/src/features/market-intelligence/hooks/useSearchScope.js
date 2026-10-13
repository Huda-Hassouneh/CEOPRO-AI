import { useQuery } from '@tanstack/react-query';
import { searchScopeApi } from '../api/searchScopeApi.js';

export function useSearchScope() {
  return useQuery({ queryKey: ['search-scope'], queryFn: searchScopeApi.getSearchScope });
}
