"""Durable original React setup choices. Uses the existing tenant connection/RLS.

Profile completion never provisions subscriptions, entitlements or credits.
Existing completed companies retain their completion marker unchanged.
"""
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int = Field(ge=1, le=5)
    expected_revision: int = Field(ge=0)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    city: str | None = Field(default=None, min_length=1, max_length=100)
    language: Literal["en", "ar"] | None = None
    industry: Literal["retail", "tech", "manufacturing", "restaurants", "healthcare", "other"] | None = None
    businessSize: Literal["1-50", "51-200", "201+"] | None = None
    annualRevenue: Literal["under-100k", "100k-500k", "500k-1m", "1m-10m", "10m-50m", "50m+"] | None = None
    objectives: list[Literal["competitors", "forecasting", "knowledge"]] | None = Field(default=None, min_length=1, max_length=3)
    selectedPlan: str | None = Field(default=None, min_length=1, max_length=100)
    billingPeriod: Literal["monthly", "three-months", "six-months"] | None = None

    @model_validator(mode="after")
    def required_choices(self):
        required={1:("country","city","language"),2:("industry",),3:("businessSize","annualRevenue"),4:("objectives",),5:("selectedPlan","billingPeriod")}[self.step]
        values=self.model_dump(exclude_none=True,exclude={"step","expected_revision"})
        if set(values) != set(required) or any(isinstance(v,str) and not v.strip() for v in values.values()):
            raise ValueError("Provide exactly the required choices for this step")
        if self.objectives and len(set(self.objectives)) != len(self.objectives):
            raise ValueError("Objectives must be distinct")
        return self

def state(conn, tenant_id, *, lock=False):
    with conn.cursor() as cur:
        cur.execute("SELECT onboarding_profile,onboarding_completed_at FROM companies WHERE tenant_id=%s" + (" FOR UPDATE" if lock else ""), (tenant_id,))
        row=cur.fetchone()
    if not row: raise HTTPException(404,"Company not found.")
    profile=row[0] or {}
    highest=int(profile.get("highestCompletedStep",0))
    return {**profile,"revision":int(profile.get("revision",0)),"highestCompletedStep":highest,"currentStep":min(highest+1,6),"isComplete":row[1] is not None}

def _audit(conn,tenant_id,user_id,action,changed):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json) VALUES(%s,%s,%s,'companies',%s,%s::jsonb)",(tenant_id,user_id,action,tenant_id,json.dumps(changed)))

def save(conn,tenant_id,user_id,body):
    current=state(conn,tenant_id,lock=True)
    if current["isComplete"]: raise HTTPException(409,"Onboarding is already complete. Use company settings or Billing.")
    values=body.model_dump(exclude_none=True,exclude={"step","expected_revision"})
    if current["revision"] != body.expected_revision:
        # Exact retried writes are harmless; a stale different request cannot overwrite.
        if current["highestCompletedStep"] >= body.step and all(current.get(k)==v for k,v in values.items()): return current
        raise HTTPException(409,"Onboarding changed. Reload the saved progress.")
    if body.step > current["highestCompletedStep"]+1: raise HTTPException(409,"Complete the preceding onboarding steps first.")
    if body.step==5:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM usage_plans WHERE plan_key=%s AND is_active AND (self_serve OR plan_key='custom')",(body.selectedPlan,))
            if not cur.fetchone(): raise HTTPException(422,"Choose an available catalog plan.")
            if body.selectedPlan != 'custom':
                cur.execute("SELECT 1 FROM billing_plan_prices WHERE plan_key=%s AND period_code=%s",(body.selectedPlan,body.billingPeriod))
                if not cur.fetchone(): raise HTTPException(422,"Choose an available billing term.")
    updated={k:v for k,v in current.items() if k not in {'currentStep','isComplete'}}
    updated.update(values,revision=current['revision']+1,highestCompletedStep=max(current['highestCompletedStep'],body.step))
    with conn.cursor() as cur:
        cur.execute("UPDATE companies SET onboarding_profile=%s::jsonb WHERE tenant_id=%s",(json.dumps(updated),tenant_id))
    _audit(conn,tenant_id,user_id,'ONBOARDING_STEP_SAVED',{'step':body.step,'revision':updated['revision']})
    return state(conn,tenant_id)

def complete(conn,tenant_id,user_id):
    from src.ai.core import usage
    current=state(conn,tenant_id,lock=True)
    if current['isComplete']: return current
    if current['highestCompletedStep']<5: raise HTTPException(409,"Complete your profile and choose a plan first.")
    effective=usage.get_plan(conn,tenant_id)
    if not effective.get('assigned') or effective.get('status') not in usage.ACCESS_GRANTING_STATUSES or effective.get('plan_key')!=current.get('selectedPlan'):
        raise HTTPException(409,"The selected plan is not active. Finish verified Checkout, or explicitly choose your current available trial. A quote request alone grants no access.")
    with conn.cursor() as cur:
        cur.execute("UPDATE companies SET onboarding_completed_at=CURRENT_TIMESTAMP WHERE tenant_id=%s AND onboarding_completed_at IS NULL",(tenant_id,))
    _audit(conn,tenant_id,user_id,'ONBOARDING_COMPLETED',{'revision':current['revision'],'plan_key':effective['plan_key'],'status':effective['status']})
    return state(conn,tenant_id)
