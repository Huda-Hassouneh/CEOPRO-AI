import { productsRepo } from "../repo/products.repo.js";
import type { ProductScope } from "../types/products.types.js";
import type { ProductCreate, ProductUpdate, ProductList } from "../types/products.validation.js";
export const listProducts = (scope: ProductScope, query: ProductList) => productsRepo.list(scope, query);
export const getProduct = (scope: ProductScope, id: string) => productsRepo.get(scope, id);
export const createProduct = (scope: ProductScope, input: ProductCreate) => productsRepo.create(scope, input);
export const updateProduct = (scope: ProductScope, id: string, input: ProductUpdate) => productsRepo.update(scope, id, input);
export const archiveProduct = (scope: ProductScope, id: string, version: number, restore = false) => productsRepo.archive(scope, id, version, restore);
