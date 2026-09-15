const product = (id,name,categoryKey,typeKey,price,download,upload,contractKey,availabilityKey,descriptionKey,demand) => ({ id,name,provider:'Orange',domain:'orange.jo',categoryKey,typeKey,statusKey:'marketScoped.common.active',price,download,upload,contractKey,availabilityKey,website:'https://www.orange.jo',descriptionKey,demand,average:[2,3,4,5,6,7,8,8,9,10,11,12] });
export const competitorProducts = {
  orange: [
    product('product-1','Ultra Speed 500','marketScoped.category.homeInternet','marketScoped.type.fiber','22.00','500 Mbps','100 Mbps','marketScoped.product.contract12','marketScoped.product.nationwide','marketProductData.ultra500',[3,5,8,8,10,12,14,13,15,15,17,19]),
    product('product-2','Ultra Speed 250','marketScoped.category.homeInternet','marketScoped.type.fiber','16.00','250 Mbps','50 Mbps','marketScoped.product.contract12','marketScoped.product.nationwide','marketProductData.ultra250',[2,3,5,6,7,8,9,10,11,12,13,14]),
    product('product-3','5G Postpaid 50','marketScoped.category.mobile','marketScoped.type.postpaid','18.00','5G','5G','marketScoped.product.contract12','marketScoped.product.majorCities','marketProductData.postpaid50',[3,4,5,7,8,9,10,11,12,14,15,16]),
    product('product-4','5G Postpaid 30','marketScoped.category.mobile','marketScoped.type.postpaid','12.00','5G','5G','marketScoped.product.contract12','marketScoped.product.majorCities','marketProductData.postpaid30',[2,3,4,5,6,8,8,9,10,11,12,13]),
    product('product-5','Orange TV','marketScoped.category.digitalServices','marketScoped.type.tv','7.00','-','-','marketScoped.product.monthly','marketScoped.product.nationwide','marketProductData.orangeTv',[2,2,3,4,5,5,6,7,7,8,9,10]),
  ],
  zain: [],
  umniah: [],
};
export const opportunitySummary = [
  {id:'total',labelKey:'market.reference.totalOpportunities',value:'18',trend:'6'},
  {id:'potential',labelKey:'market.final.potential',value:'7',trend:'3'},
  {id:'size',labelKey:'market.reference.estimatedMarketSize',value:'245M JOD',trend:'12%'},
  {id:'growth',labelKey:'market.reference.averageDemandGrowth',value:'+18%',trend:'5%'},
];
const opp = (id,key,categoryKey,potentialKey,marketSize,growth,competitionKey,trend,competitorActivity,insightKeys,actionKeys) => ({id,key,titleKey:'marketScoped.opportunityData.'+key+'.title',shortTitleKey:'marketScoped.opportunityData.'+key+(key==='homeDemand'?'.short':'.title'),typeKey:'marketScoped.opportunityData.'+key+'.type',descriptionKey:'marketScoped.opportunityData.'+key+'.description',categoryKey,potentialKey,marketSize,growth,competitionKey,trend,competitorActivity,insightKeys,actionKeys});
export const opportunities = [
  opp('opportunity-1','homeDemand','marketScoped.category.homeInternet','marketScoped.common.high','45M JOD','+28%','marketScoped.common.low',[14,24,39,58,76,84,98],[13,9,7,5,5,3],[1,2,3,4].map(n=>'marketScoped.opportunityData.homeDemand.insight'+n),[1,2,3].map(n=>'marketScoped.opportunityData.homeDemand.action'+n)),
  opp('opportunity-2','smartBundle','marketScoped.category.smartHome','marketScoped.common.high','32M JOD','+24%','marketScoped.common.low',[12,20,28,39,52,65,76],[10,9,8,7,6,5],['marketScoped.opportunityData.smartBundle.insight'],['marketScoped.opportunityData.smartBundle.action']),
  opp('opportunity-3','mobileBundle','marketScoped.category.mobile','marketScoped.common.medium','28M JOD','+18%','marketScoped.common.medium',[12,18,26,35,44,52,63],[8,8,7,6,5,5],['marketScoped.opportunityData.mobileBundle.insight'],['marketScoped.opportunityData.mobileBundle.action']),
  opp('opportunity-4','gaming','marketScoped.category.homeInternet','marketScoped.common.medium','18M JOD','+22%','marketScoped.common.medium',[8,14,20,31,45,56,68],[9,8,8,7,6,5],['marketScoped.opportunityData.gaming.insight'],['marketScoped.opportunityData.gaming.action']),
  opp('opportunity-5','business','marketScoped.category.business','marketScoped.common.medium','25M JOD','+20%','marketScoped.common.high',[10,18,27,35,45,58,70],[12,11,10,9,8,7],['marketScoped.opportunityData.business.insight'],['marketScoped.opportunityData.business.action']),
  opp('opportunity-6','student','marketScoped.category.mobile','marketScoped.common.medium','12M JOD','+15%','marketScoped.common.high',[8,12,20,32,42,50,60],[13,12,11,10,9,8],['marketScoped.opportunityData.student.insight'],['marketScoped.opportunityData.student.action']),
  opp('opportunity-7','streaming','marketScoped.category.digitalServices','marketScoped.common.medium','20M JOD','+17%','marketScoped.common.medium',[10,15,23,30,40,51,62],[8,8,7,7,6,5],['marketScoped.opportunityData.streaming.insight'],['marketScoped.opportunityData.streaming.action']),
  opp('opportunity-8','security','marketScoped.category.smartHome','marketScoped.common.high','15M JOD','+26%','marketScoped.common.low',[9,18,28,40,55,70,85],[6,6,5,5,4,3],['marketScoped.opportunityData.security.insight'],['marketScoped.opportunityData.security.action']),
  opp('opportunity-9','cloud','marketScoped.category.digitalServices','marketScoped.common.low','10M JOD','+14%','marketScoped.common.high',[8,12,18,24,31,39,46],[12,11,10,9,8,7],['marketScoped.opportunityData.cloud.insight'],['marketScoped.opportunityData.cloud.action']),
  opp('opportunity-10','backup','marketScoped.category.business','marketScoped.common.medium','18M JOD','+18%','marketScoped.common.medium',[10,16,24,34,46,58,71],[9,8,7,7,6,5],['marketScoped.opportunityData.backup.insight'],['marketScoped.opportunityData.backup.action']),
];
export const leaderboard = [
  ['stratos-analytics','Stratos Analytics','stratos.com',92,88,95,94.5,2],['metricflow','MetricFlow','metricflow.io',78,85,82,83.2,1],['novaquery','NovaQuery','novaquery.com',85,82,75,76.8,-1],['cloudsight-data','CloudSight Data','cloudsight.co',55,70,58,61.4,0],['orange','Orange','orange.jo',68,65,60,59.8,3],['zain','Zain','zain.com',60,68,55,58.1,1],['umniah','Umniah','umniah.com',62,63,52,55.6,-2],['vortex-data','Vortex Data','vortexdata.co',58,60,50,52.3,0],['fibernet','FiberNet','fibernet.jo',50,57,48,48.6,1],['linkplus','LinkPlus','linkplus.jo',45,52,46,43.7,-1],
].map(([id,name,domain,price,sentiment,activity,score,movement])=>({id,name,domain,price,sentiment,activity,score,movement}));
