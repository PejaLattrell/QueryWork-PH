const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/charts.js'), 'utf8');

function setup(readyState) {
  const handlers = new Map(), created = [], destroyed = [];
  const trends = { daily_volume: [{post_date:'2026-10-01', normalized_role:'Backend Engineer', job_count:1}], top_skills: [{skill:'python', mention_count:1, avg_salary_usd:100000}], salary_benchmarks: [], work_arrangements: [{work_arrangement:'Remote',job_count:1,percentage:100}] };
  const elements = Object.fromEntries(['velocity-chart','skills-chart','salary-chart','arrangement-chart'].map(id=>[id,{id,closest:()=>({querySelector:()=>({classList:{toggle(){}}})})}]));
  elements['chart-data'] = {textContent:JSON.stringify({trends,days:30})};
  const document = {readyState,getElementById:id=>elements[id] ?? null,addEventListener:(name,fn)=>handlers.set(name,fn)};
  class Chart {constructor(canvas,config){created.push({canvas,config});} destroy(){destroyed.push(this);}}
  const window = {matchMedia:()=>({matches:false}),Chart};
  new Function('window','document','Chart',source)(window,document,Chart);
  return {handlers,created,destroyed,elements};
}
test('charts initialize even when DOMContentLoaded has already fired', () => {
  const state=setup('complete');
  assert.deepEqual(state.created.map(row=>row.config.type),['line','bar','bar','doughnut']);
  assert.equal(state.handlers.has('htmx:afterSwap'),false);
  state.handlers.get('htmx:afterSettle')({detail:{target:{id:'dashboard-content'}}});
  assert.equal(state.created.length,8);
  assert.equal(state.destroyed.length,4);
});
test('deferred startup and table pagination do not duplicate chart instances', () => {
  const state=setup('loading');
  assert.equal(state.created.length,0);
  state.handlers.get('DOMContentLoaded')();
  assert.equal(state.created.length,4);
  state.handlers.get('htmx:afterSettle')({detail:{target:{id:'job-explorer'}}});
  assert.equal(state.created.length,4);
});
