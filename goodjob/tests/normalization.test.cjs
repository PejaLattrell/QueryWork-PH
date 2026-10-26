const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../n8n/normalize.js'), 'utf8');
const functions = new Function('require', script.split('const rates = JSON.parse')[0] + '\nreturn {parseSalary,skillsFrom,classify,seniority,normalize};')(require);
const { parseSalary, skillsFrom, classify, seniority, normalize } = functions;

test('annual, monthly and hourly salary normalization handles ranges', () => {
  assert.equal(parseSalary('USD 120k - 160k per year').salary_annual_usd, 140000);
  assert.equal(parseSalary('$120-160k').salary_min, 120000);
  assert.equal(parseSalary('$50 - $70 /hr').salary_annual_usd, 124800);
  assert.equal(parseSalary('PHP 100,000 - 140,000 /month', { PHP: 0.017 }).salary_annual_usd, 24480);
  assert.equal(parseSalary('EUR 60000-80000').salary_annual_usd, null);
  assert.equal(parseSalary('competitive').salary_min, null);
  assert.equal(parseSalary('100-150').salary_min, null);
  assert.equal(parseSalary('US$100k-120k').salary_currency, 'USD');
  assert.equal(parseSalary('C$100k-120k').salary_currency, 'CAD');
  assert.equal(parseSalary('S$100k-120k').salary_currency, 'SGD');
});
test('skill aliases and boundaries avoid Java/JavaScript collisions', () => {
  const skills = skillsFrom('JavaScript, Next.js, Node.js, PostgreSQL, C++, C# and Python. Dockerized services.');
  assert.ok(skills.includes('javascript') && skills.includes('nextjs') && skills.includes('postgresql'));
  assert.ok(skills.includes('c++') && skills.includes('c#'));
  assert.ok(!skills.includes('java') && !skills.includes('docker'));
});
test('role and seniority classifiers use specific roles first', () => {
  assert.equal(classify('Senior Machine Learning Engineer'), 'AI/ML Engineer');
  assert.equal(classify('Senior Data Platform Engineer'), 'Data Engineer');
  assert.equal(classify('Full-stack Software Engineer'), 'Fullstack Engineer');
  assert.equal(seniority('Principal Backend Engineer'), 'Lead/Principal');
});
test('fingerprints are deterministic; unsafe URLs and invalid dates are rejected', () => {
  const raw = {id:1,title:'Senior Backend Engineer',company_name:'Example Co',url:'https://example.com/job',publication_date:'2026-01-01',description:'Python and FastAPI',candidate_required_location:'United States'};
  const a = normalize(raw,'remotive',{}), b = normalize({...raw,title:'senior backend engineer',company_name:'EXAMPLE CO'},'remotive',{});
  assert.equal(a.fingerprint,b.fingerprint);
  assert.match(a.fingerprint,/^[a-f0-9]{64}$/);
  assert.equal(a.country,'US');
  assert.equal(normalize({...raw,url:'javascript:alert(1)'},'remotive',{}),null);
  assert.equal(normalize({...raw,publication_date:'invalid'},'remotive',{}),null);
});
test('feed failures and empty feeds produce a loggable envelope', () => {
  const evaluate = new Function('require','$env','$',script);
  const result = evaluate(require,{},name=>({first:()=>({json:name==='Fetch Remotive'?{error:'timeout'}:{statusCode:200,body:{data:[]}}})}));
  assert.equal(result[0].json.jobs.length,0);
  assert.equal(result[0].json.errors.length,1);
});
test('cross-source items merge and same-source duplicates deduplicate', () => {
  const evaluate = new Function('require','$env','$',script);
  const raw = {id:1,title:'Python Developer',company_name:'Example',url:'https://example.com/job',publication_date:'2026-01-01',description:'Python'};
  const result = evaluate(require,{},name=>({first:()=>({json:{statusCode:200,body:name==='Fetch Remotive'?{jobs:[raw,raw]}:{data:[{...raw,slug:'example',created_at:1767225600,remote:false}]}}})}));
  assert.equal(result[0].json.jobs_found,3);
  assert.equal(result[0].json.jobs.length,2);
});
test('workflow JSON has both triggers, batch upsert and connected failure logging', () => {
  const workflow=JSON.parse(fs.readFileSync(path.join(__dirname,'../n8n/goodjob_scraper_workflow.json'),'utf8'));
  assert.equal(workflow.nodes.filter(n=>n.type.endsWith('scheduleTrigger') || n.type.endsWith('webhook')).length,2);
  assert.equal(workflow.connections['Normalize Jobs'].main[1][0].node,'Log Normalization Failure');
  assert.equal(workflow.nodes.find(n=>n.name==='Batch Upsert').onError,'continueRegularOutput');
  const names=new Set(workflow.nodes.map(n=>n.name));
  for(const c of Object.values(workflow.connections)) for(const branch of c.main) for(const dest of branch) assert.ok(names.has(dest.node));
});
test('batching respects 100-row bounds and preserves empty-run logging', () => {
  const workflow=JSON.parse(fs.readFileSync(path.join(__dirname,'../n8n/goodjob_scraper_workflow.json'),'utf8'));
  const build=new Function('$input',workflow.nodes.find(n=>n.name==='Build Batches').parameters.jsCode);
  assert.deepEqual(build({first:()=>({json:{jobs:Array.from({length:201},(_,i)=>i)}})}).map(item=>item.json.jobs.length),[100,100,1]);
  assert.deepEqual(build({first:()=>({json:{jobs:[]}})}),[{json:{jobs:[]}}]);
});
test('partial write failures produce a failed run with accurate successful counts', () => {
  const workflow=JSON.parse(fs.readFileSync(path.join(__dirname,'../n8n/goodjob_scraper_workflow.json'),'utf8'));
  const summarize=new Function('$input','$',workflow.nodes.find(n=>n.name==='Summarize Run').parameters.jsCode);
  const select=name=>({first:()=>({json:{jobs_found:101,errors:[]}}),all:()=>[{json:{jobs:Array(100)}},{json:{jobs:Array(1)}}]});
  const result=summarize({all:()=>[{json:{statusCode:201}},{json:{error:'timeout'}}]},select)[0].json;
  assert.equal(result.status,'failed');
  assert.equal(result.jobs_found,101);
  assert.equal(result.jobs_upserted,100);
  assert.match(result.error_message,/Batch 2/);
});
