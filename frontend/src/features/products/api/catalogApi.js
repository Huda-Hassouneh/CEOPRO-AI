import httpClient from '../../../shared/lib/httpClient.js';
// Original catalog UI -> canonical Python product authority; no Node endpoints.
const payload=(input)=>({product_name:input.name,sku:input.sku,barcode:input.gtin,current_price:input.price,cost_price:input.costPrice,currency:input.currency,brand:input.brand,category:input.category,description:input.description,...(input.expectedVersion?{expected_version:input.expectedVersion}:{})});
export const productsApi={
 list:async({signal,...params}={})=>(await httpClient.get('/catalog/products',{params,signal})).data,
 getById:async(id,{signal}={})=>(await httpClient.get(`/catalog/products/${encodeURIComponent(id)}`,{signal})).data,
 create:async(input)=>(await httpClient.post('/products',payload(input))).data,
 update:async({id,...input})=>(await httpClient.patch(`/products/${encodeURIComponent(id)}`,payload(input))).data,
 archive:async({id,expectedVersion})=>(await httpClient.post(`/catalog/products/${encodeURIComponent(id)}/archive`,{expectedVersion})).data,
 restore:async({id,expectedVersion})=>(await httpClient.post(`/catalog/products/${encodeURIComponent(id)}/restore`,{expectedVersion})).data,
 previewGtins:async(file)=>{const data=new FormData();data.append('file',file);return(await httpClient.post('/catalog/products/gtin-import/preview',data,{headers:{'Content-Type':undefined}})).data;},
 applyGtins:async(input)=>(await httpClient.post('/catalog/products/gtin-import/apply',input)).data,
};
