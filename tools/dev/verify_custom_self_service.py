"""Compare original Node validation/review/price/payment decisions without services."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from src.ai.billing import self_service, custom_offers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--legacy-backend', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    dest, legacy = Path(args.output).resolve(), Path(args.legacy_backend).resolve()
    assert legacy != dest and legacy not in dest.parents
    dest.mkdir(parents=True, exist_ok=True)
    policy = dict(self_service.DEFAULTS, monthlyInfrastructureCost=0, activePayingTenants=1, estimatedOtherCost=0,
                  enforceVendorCostRatioFloor=False, maxVendorCostRevenueRatio='.2',
                  billingOptions=[{'period': k, 'months': v[0], 'discountPercent': v[1]} for k,v in self_service.TERMS.items()])
    now = datetime.now(timezone.utc)
    rows, python = [], []
    for name, quantity, overrides, unverified, period in [
        ('automatic',10,{},False,'monthly'), ('quota',500001,{},False,'monthly'),
        ('price',10,{'maxAutomaticMonthlyPrice':'35'},False,'monthly'),
        ('price-equality',10,{'maxAutomaticMonthlyPrice':'36'},False,'monthly'),
        ('unverified',10,{},True,'monthly'),
        ('feature-override',10,{'featureLimits':{'connected_data_sources':{'max':9}}},False,'monthly'),
        ('invalid-step',9,{'featureLimits':{'connected_data_sources':{'step':2}}},False,'monthly'),
        ('three-months',10,{},False,'three-months'), ('six-months',10,{},False,'six-months'),
        ('stored-policy',10,{'fixedPlatformFee':'17','fxRate':'.7','targetGrossMargin':'.25',
                             'fxSource':'synthetic approved rate','fxVersion':'synthetic-v2'},False,'monthly'),
    ]:
        effective = {**deepcopy(policy), **overrides}
        binding = {'binding_id':'binding','feature_code':'connected_data_sources','rate_id':'rate','unit_cost_usd':'1',
            'cost_is_final':not unverified,'verified_at':now.date().isoformat(),'updated_at':now.isoformat(),
            'provider':'synthetic','operation':'source-month','unit':'request','usage_basis':'limit_value',
            'units_per_feature_unit':'1','operational_multiplier':'1','variability_reserve':'1',
            'cost_category':'vendor','usage_assumption':{},'rate_source':'synthetic differential'}
        configuration = {'limits':{'connected_data_sources':quantity},'enabledFeatures':[],'refreshFrequency':None,'billingPeriod':period}
        try:
            actual = self_service.calculate(configuration, {'policy':{'policy_version_id':'synthetic','self_service_policy':effective},'bindings':[binding]})
            actual = {'valid':True,'monthlyPrice':actual['monthlyPrice'],'price':actual['price'],
                'paymentAmount':actual['paymentAmount'],'reasons':actual['reasons'],'checkout':not actual['reviewRequired']}
        except custom_offers.CustomOfferError:
            actual = {'valid':False}
        python.append(actual)
        rows.append({'name':name,'policy':effective,'definitions':[{'id':'feature','code':'connected_data_sources','type':'limit'}],
            'input':{'features':[{'featureId':'feature','limitValue':quantity}],'billingPeriod':period},
            'vendorRates':[{'id':'rate','featureId':'feature','vendor':'synthetic','service':'source-month','billingUnit':'request',
                'unitCost':'1','currency':'USD','operationalMultiplier':'1','variabilityReserve':'1',
                'verificationStatus':'unconfirmed' if unverified else 'confirmed','feature':{'code':'connected_data_sources'}}]})
    (dest/'inputs.json').write_text(json.dumps(rows))
    subprocess.run(['node',str(ROOT/'tools/dev/legacy_custom_self_service_reference.mjs'),str(legacy),str(dest/'inputs.json'),str(dest/'node.json')],check=True)
    reference = json.loads((dest/'node.json').read_text())
    for row, expected in zip(reference['results'], python):
        actual = row['actual']
        assert actual['success'] == expected['valid'], row['name']
        if not expected['valid']:
            continue
        actual = actual['data']
        for field in ('monthlyPrice','price','paymentAmount'):
            assert Decimal(str(actual[field])) == Decimal(expected[field]), (row['name'],field,actual,expected)
        assert actual['manualReviewReasons'] == expected['reasons'], row['name']
        assert actual['eligibleForInstantCheckout'] == expected['checkout'], row['name']
    print(f"PASS: {len(rows)} original Node validation/price/review/payment parity vectors; {dest}")


if __name__ == '__main__':
    main()
