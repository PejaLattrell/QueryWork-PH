"""Rebuild the importable workflow and its SDK validation source from the same nodes."""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
nodes = []
connections = {}


def add(name, kind, version, parameters, x, y, **extra):
    nodes.append(dict(id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'goodjob/' + name)), name=name,
                      type='n8n-nodes-base.' + kind, typeVersion=version, parameters=parameters,
                      position=[x, y], **extra))


def link(source, target, output=0, input_index=0):
    main = connections.setdefault(source, {'main': []})['main']
    while len(main) <= output:
        main.append([])
    main[output].append(dict(node=target, type='main', index=input_index))


def code(name, js, x, y, **extra):
    add(name, 'code', 2, dict(mode='runOnceForAllItems', jsCode=js), x, y, **extra)


def http(name, method, url, x, y, body=None, prefer=None, database=True, **extra):
    headers = [{'name': 'User-Agent', 'value': 'GoodJob/1.0 (public job market analytics)'}]
    if database:
        headers += [dict(name='apikey', value='={{ $env.SUPABASE_SERVICE_ROLE_KEY }}'),
                    dict(name='Authorization', value='=Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}')]
    if prefer:
        headers.append(dict(name='Prefer', value=prefer))
    params = dict(method=method, url=url, sendHeaders=True, headerParameters={'parameters': headers},
                  options={'timeout': 30000, 'response': {'response': {'fullResponse': True, 'responseFormat': 'json' if method == 'GET' else 'text'}}})
    if body is not None:
        params.update(sendBody=True, contentType='json', specifyBody='json', jsonBody=body)
    add(name, 'httpRequest', 4.4, params, x, y, **extra)


add('Every Six Hours', 'scheduleTrigger', 1.3, {'rule': {'interval': [{'field': 'cronExpression', 'expression': '0 */6 * * *'}]}}, 0, 0)
add('On Demand', 'webhook', 2.1, dict(httpMethod='POST', path='goodjob-trigger', responseMode='onReceived', options={'responseData': '{"accepted":true}'}), 0, 240,
    webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, 'goodjob-trigger')))
code('Prepare Run', "const { randomUUID } = require('crypto'); return [{json: {id: randomUUID(), source: 'remotive+arbeitnow', status: 'running'}}];", 240, 100)
http('Start Run', 'POST', '={{ $env.SUPABASE_URL }}/rest/v1/scrape_runs?on_conflict=id', 480, 100,
     '={{ JSON.stringify($json) }}', 'resolution=merge-duplicates,return=minimal', retryOnFail=True, maxTries=3)
http('Fetch Remotive', 'GET', 'https://remotive.com/api/remote-jobs?category=software-dev&limit=50', 720, 0,
     database=False, onError='continueRegularOutput', retryOnFail=True, maxTries=3)
http('Fetch Arbeitnow', 'GET', 'https://www.arbeitnow.com/api/job-board-api', 720, 240,
     database=False, onError='continueRegularOutput', retryOnFail=True, maxTries=3)
add('Merge Feeds', 'merge', 3.2, dict(mode='append', numberInputs=2), 960, 100)
code('Normalize Jobs', (ROOT / 'normalize.js').read_text(encoding='utf-8'), 1200, 100, onError='continueErrorOutput')
code('Build Batches', "const jobs = $input.first().json.jobs; const batches = []; for (let i=0;i<jobs.length;i+=100) batches.push({json:{jobs:jobs.slice(i,i+100)}}); return batches.length ? batches : [{json:{jobs:[]}}];", 1440, 100)
http('Batch Upsert', 'POST', '={{ $env.SUPABASE_URL }}/rest/v1/job_postings?on_conflict=fingerprint', 1680, 100,
     '={{ JSON.stringify($json.jobs) }}', 'resolution=merge-duplicates,return=minimal',
     onError='continueRegularOutput', retryOnFail=True, maxTries=3)
code('Summarize Run', "const data = $('Normalize Jobs').first().json; const batches = $('Build Batches').all(); const errors = [...data.errors]; let stored=0; $input.all().forEach((item,i)=>{ if(item.json.error || item.json.statusCode >= 400 || !item.json.statusCode) errors.push('Batch '+(i+1)+' upsert failed'); else stored+=batches[i].json.jobs.length; }); return [{json:{status:errors.length?'failed':'completed',jobs_found:data.jobs_found,jobs_upserted:stored,error_message:errors.length?errors.join('; '):null,completed_at:new Date().toISOString()}}];", 1920, 100)
http('Complete Run', 'PATCH', "={{ $env.SUPABASE_URL }}/rest/v1/scrape_runs?id=eq.{{ $('Prepare Run').first().json.id }}", 2160, 100,
     '={{ JSON.stringify($json) }}', 'return=minimal', retryOnFail=True, maxTries=3)
http('Log Normalization Failure', 'PATCH', "={{ $env.SUPABASE_URL }}/rest/v1/scrape_runs?id=eq.{{ $('Prepare Run').first().json.id }}", 1440, 400,
     '={{ JSON.stringify({status:"failed",error_message:"Normalization failed; inspect the n8n execution for details",completed_at:$now.toISO()}) }}', 'return=minimal', retryOnFail=True, maxTries=3)
link('Every Six Hours', 'Prepare Run')
link('On Demand', 'Prepare Run')
link('Prepare Run', 'Start Run')
link('Start Run', 'Fetch Remotive')
link('Start Run', 'Fetch Arbeitnow')
link('Fetch Remotive', 'Merge Feeds')
link('Fetch Arbeitnow', 'Merge Feeds', input_index=1)
for left, right in zip(['Merge Feeds','Normalize Jobs','Build Batches','Batch Upsert','Summarize Run'], ['Normalize Jobs','Build Batches','Batch Upsert','Summarize Run','Complete Run']):
    link(left, right)
link('Normalize Jobs', 'Log Normalization Failure', output=1)
workflow = dict(name='GoodJob — Job Market Ingestion', nodes=nodes, connections=connections,
                active=False, settings={'executionOrder': 'v1', 'timezone': 'Asia/Manila', 'executionTimeout': 600}, pinData={})
(ROOT / 'goodjob_scraper_workflow.json').write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding='utf-8')


def sdk_value(value):
    if isinstance(value, str) and value.startswith('='):
        return 'expr(' + json.dumps(value[1:]) + ')'
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k)+':'+sdk_value(v) for k,v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ','.join(sdk_value(v) for v in value) + ']'
    return json.dumps(value)


lines = ["import {workflow,node,trigger,merge,expr} from '@n8n/workflow-sdk';"]
for i, n in enumerate(nodes):
    factory = 'trigger' if n['type'].endswith(('scheduleTrigger','webhook')) else 'merge' if n['type'].endswith('.merge') else 'node'
    config = {k:v for k,v in n.items() if k not in ('type','typeVersion','id','webhookId')}
    example = [{'statusCode':200,'body':{}}]
    if n['name'] in ('Build Batches','Normalize Jobs'):
        example = [{'jobs': [], 'jobs_found': 0, 'errors': []}]
    if n['name'] == 'Prepare Run':
        example = [{'id': '00000000-0000-0000-0000-000000000001', 'source': 'remotive+arbeitnow', 'status': 'running'}]
    args = {'version': n['typeVersion'], 'config': config, 'output': example}
    if factory != 'merge':
        args['type'] = n['type']
    lines.append(f'const n{i} = {factory}({sdk_value(args)});')
indices = {n['name']:i for i,n in enumerate(nodes)}
lines.append("export default workflow('goodjob-ingestion','GoodJob — Job Market Ingestion')")
for source, c in connections.items():
    for output, destinations in enumerate(c['main']):
        for dest in destinations:
            source_ref = f'n{indices[source]}' + ('.output(1)' if output else '')
            target_ref = f'n{indices[dest["node"]]}' + (f'.input({dest["index"]})' if dest['node']=='Merge Feeds' else '')
            lines.append(f'.add({source_ref}.to({target_ref}))')
lines[-1] += ';'
(ROOT / 'workflow.sdk.js').write_text('\n'.join(lines), encoding='utf-8')
print(f'Generated {len(nodes)} nodes.')
