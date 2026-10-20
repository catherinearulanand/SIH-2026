"""Strict, dependency-free validation for Track 2 integration artifacts."""
import hashlib
import json
import re


class ContractError(ValueError):
    def __init__(self,code,message,status=422,current_version=None):
        super().__init__(message)
        self.code=code;self.message=message;self.status=status;self.current_version=current_version


HEX64=re.compile(r'^[0-9a-f]{64}$')
IDENTIFIER=re.compile(r'^[A-Za-z0-9_-]{1,80}$')
RECOMMENDATION_FIELDS={
    'snapshot_id','snapshot_sha256','input_revision','forecast_run_id','plan_id','graph_version','scenario_id',
    'constraints_version','source_site_id','destination_site_id','item_id','proposed_quantity','solver_status',
    'warnings','explanation','evidence_digest'
}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text(value,name,limit=80):
    if not isinstance(value,str) or not value or len(value)>limit:
        raise ContractError('INVALID_INPUT',f'{name} must be 1..{limit} characters')
    return value


def identifier(value,name):
    value=text(value,name)
    if not IDENTIFIER.fullmatch(value):
        raise ContractError('INVALID_INPUT',f'{name} contains unsupported characters')
    return value


def string_list(value,name):
    if not isinstance(value,list) or len(value)>50 or any(not isinstance(v,str) or len(v)>500 for v in value):
        raise ContractError('INVALID_INPUT',f'{name} must be an array of at most 50 bounded strings')
    return value


def validate_recommendation(value):
    if not isinstance(value,dict) or set(value)!=RECOMMENDATION_FIELDS:
        unknown=sorted(set(value or {})-RECOMMENDATION_FIELDS) if isinstance(value,dict) else []
        missing=sorted(RECOMMENDATION_FIELDS-set(value or {})) if isinstance(value,dict) else sorted(RECOMMENDATION_FIELDS)
        raise ContractError('INVALID_INPUT',f'Recommendation fields mismatch; missing={missing}, unknown={unknown}')
    result={k:identifier(value[k],k) for k in ('snapshot_id','forecast_run_id','plan_id','graph_version','scenario_id',
                                                'constraints_version','source_site_id','destination_site_id','item_id')}
    if result['source_site_id']==result['destination_site_id']:
        raise ContractError('INVALID_INPUT','Source and destination must differ')
    for field in ('snapshot_sha256','evidence_digest'):
        candidate=text(value[field],field,64)
        if not HEX64.fullmatch(candidate):
            raise ContractError('INVALID_INPUT',field+' must be lowercase SHA-256 hex')
        result[field]=candidate
    if type(value['input_revision']) is not int or value['input_revision']<0:
        raise ContractError('INVALID_INPUT','input_revision must be a nonnegative integer')
    if type(value['proposed_quantity']) is not int or not 1<=value['proposed_quantity']<=10_000_000:
        raise ContractError('INVALID_INPUT','proposed_quantity must be 1..10000000 canonical units')
    solver=text(value['solver_status'],'solver_status',32)
    if solver not in ('OPTIMAL','FEASIBLE_TIMEOUT'):
        raise ContractError('NO_FEASIBLE_PLAN','Only OPTIMAL or labelled FEASIBLE_TIMEOUT can support a recommendation',409)
    result.update(input_revision=value['input_revision'],proposed_quantity=value['proposed_quantity'],solver_status=solver,
                  warnings=string_list(value['warnings'],'warnings'),explanation=string_list(value['explanation'],'explanation'))
    return result
