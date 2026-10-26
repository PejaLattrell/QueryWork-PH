const fs = require('node:fs');
const path = require('node:path');

async function main() {
  const feeds = [ ['Fetch Remotive','https://remotive.com/api/remote-jobs?category=software-dev&limit=50'], ['Fetch Arbeitnow','https://www.arbeitnow.com/api/job-board-api'] ];
  const responses = Object.fromEntries(await Promise.all(feeds.map(async ([name,url])=>{
    try {
      const response = await fetch(url,{signal:AbortSignal.timeout(30000),headers:{'User-Agent':'GoodJob/1.0 (API verification)'}});
      return [name,{statusCode:response.status,body:await response.json()}];
    } catch(error) {
      return [name,{error:error.message}];
    }
  })));
  const source=fs.readFileSync(path.join(__dirname,'../n8n/normalize.js'),'utf8');
  const evaluate=new Function('require','$env','$',source);
  const result=evaluate(require,{},name=>({first:()=>({json:responses[name]})}))[0].json;
  console.log(JSON.stringify({found:result.jobs_found,normalized:result.jobs.length,rejected:result.rejected,errors:result.errors,bySource:Object.fromEntries(['remotive','arbeitnow'].map(name=>[name,result.jobs.filter(job=>job.source===name).length]))}));
  if (result.errors.length) process.exitCode=1;
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
