"""Repeatable Node/Python differential proof. No database, provider or financial mutation."""
import argparse
from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from src.ai.billing.custom_plan_pricing import calculate_custom_plan_price,CustomPlanPricingError

def vectors():
    saved=json.loads((ROOT/'backend/tests/billing/custom_plan_pricing_runtime_vectors.json').read_text())
    rows=[{'name':v['name'],'input':v['input']} for v in saved['vectors']]
    base=deepcopy(rows[0]['input'])
    from src.ai.billing import admin
    features=sorted(set(admin._NUMERIC_CONTRACT_FEATURES)|set(admin._CUSTOM_CONTRACT_ENTITLEMENTS))
    for code in features:
        v=deepcopy(base);v['features'][0].update(featureId=code,featureCode=code);v['vendorRates'][0]['featureId']=code
        rows.append({'name':'feature:'+code,'input':v})
    for name,field,value in [('zero','estimatedUsage',0),('max-synthetic','estimatedUsage',2147483647)]:
        v=deepcopy(base);v['features'][0][field]=value;rows.append({'name':name,'input':v})
    for margin in ['0','0.9999']:
        v=deepcopy(base);v['targetGrossMargin']=margin;rows.append({'name':'margin:'+margin,'input':v})
    for amount in ['0.005','0.015','0.999999999','0.00000001']:
        v=deepcopy(base);v['vendorRates'][0]['unitCost']=amount;v.update(roundingIncrement='0',fixedPlatformFee='0');rows.append({'name':'rounding:'+amount,'input':v})
    cadence=next((deepcopy(v['input']) for v in rows if any(f.get('configuration',{}).get('monitoringFrequencyMinutes') for f in v['input']['features'])),None)
    if cadence:
        for minutes in [60,1440,10080]:
            v=deepcopy(cadence)
            for f in v['features']:
                if f.get('configuration',{}).get('monitoringFrequencyMinutes'):f['configuration']['monitoringFrequencyMinutes']=minutes
            rows.append({'name':'cadence:'+str(minutes),'input':v})
    for name,change in [('invalid-margin',{'targetGrossMargin':1}),('invalid-count',{'activePayingTenants':0}),('missing-rates',{'vendorRates':[]}),('missing-ratio',{'enforceVendorCostRatioFloor':True,'maxVendorCostRevenueRatio':None}),('negative-fee',{'fixedPlatformFee':-1}),('missing-fx',{'quoteCurrency':'JOD'})]:
        v=deepcopy(base);v.update(change);rows.append({'name':name,'input':v})
    return rows

def canonical(value):
    if isinstance(value,dict):return {k:canonical(v) for k,v in value.items() if v is not None}
    if isinstance(value,list):return [canonical(v) for v in value]
    if isinstance(value,bool):return value
    if isinstance(value,(Decimal,str,int,float)):
        try:
            number=Decimal(str(value))
            # Original Prisma Decimal uses 20 significant digits. Compare raw evidence
            # at that precision; monetary fields are already rounded to exact cents.
            with localcontext() as ctx:ctx.prec=20;return +number
        except Exception:return value
    return value

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--legacy-backend',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    dest=Path(args.output).resolve();dest.mkdir(parents=True,exist_ok=True)
    source=Path(args.legacy_backend).resolve()
    if source==dest or source in dest.parents:raise SystemExit('Evidence must be outside the read-only legacy repository')
    samples=vectors();(dest/'inputs.json').write_text(json.dumps(samples,indent=2))
    subprocess.run(['node',str(ROOT/'tools/dev/legacy_billing_reference.mjs'),str(source),str(dest/'inputs.json'),str(dest/'node.json')],check=True)
    reference=json.loads((dest/'node.json').read_text());results=[]
    for sample,node in zip(samples,reference['results']):
        try:
            actual=calculate_custom_plan_price(sample['input']);status='calculated';error=None
        except (CustomPlanPricingError,KeyError) as exc:actual=None;status='rejected';error=str(exc)
        extensions=[]
        compared=deepcopy(actual)
        if status=='calculated' and node['status']=='calculated':
            for original,current in zip(node['result'].get('infrastructureBreakdown',[]),compared.get('infrastructureBreakdown',[])):
                if 'featureCode' not in original and 'featureCode' in current:
                    code=current.pop('featureCode')
                    assert code in [f.get('featureCode') for f in sample['input']['features']]
                    extensions.append({'field':'infrastructureBreakdown.featureCode','value':code,'classification':'ADDITIVE INTERNAL EVIDENCE','basis':'Canonical feature code from the same input; no monetary or entitlement change. Not a separately approved commercial rule.'})
        passed=node['status']==status and (status=='rejected' or canonical(node['result'])==canonical(compared))
        results.append({'name':sample['name'],'status':'PASS' if passed else 'DEFECT','documented_extensions':extensions,'node':node,'python':{'status':status,'result':actual,'error':error}})
    report={'reference_sha256':reference['sha256'],'normalization':'Null/undefined omitted; numeric values compared at original Prisma Decimal 20 significant digits; no monetary tolerance','results':results}
    (dest/'differential.json').write_text(json.dumps(report,default=str,indent=2))
    failed=[r['name'] for r in results if r['status']!='PASS']
    print(f"Node/Python differential: {len(results)-len(failed)}/{len(results)} passed; evidence: {dest}")
    if failed:raise SystemExit('Unexplained differences: '+', '.join(failed))
if __name__=='__main__':main()
