const { createHash } = require('crypto');
const dictionary = {
  python: 'python', java: 'java', javascript: 'javascript|ecmascript', typescript: 'typescript',
  php: 'php', ruby: 'ruby', rust: 'rust', golang: 'golang|go language', scala: 'scala',
  kotlin: 'kotlin', swift: 'swift', 'c++': 'c\\+\\+', 'c#': 'c#|c sharp',
  react: 'react(?:\\.js)?', nextjs: 'next\\.?js', vue: 'vue(?:\\.js)?', angular: 'angular',
  svelte: 'svelte', fastapi: 'fastapi', django: 'django', flask: 'flask', laravel: 'laravel',
  nodejs: 'node\\.?js', express: 'express\\.?js', spring: 'spring boot', rails: 'rails',
  postgresql: 'postgres(?:ql)?', supabase: 'supabase', mysql: 'mysql', mongodb: 'mongo(?:db)?',
  docker: 'docker', kubernetes: 'kubernetes|k8s', aws: 'aws|amazon web services',
  gcp: 'gcp|google cloud', azure: 'azure', kafka: 'kafka', airflow: 'airflow',
  snowflake: 'snowflake', bigquery: 'bigquery', n8n: 'n8n', graphql: 'graphql', redis: 'redis',
  pytorch: 'pytorch', tensorflow: 'tensorflow', 'scikit-learn': 'scikit[ -]learn',
  spark: 'apache spark|pyspark', dbt: 'dbt', sql: 'sql', terraform: 'terraform',
  ansible: 'ansible', linux: 'linux', prometheus: 'prometheus', grafana: 'grafana',
  elasticsearch: 'elasticsearch', 'github actions': 'github actions', git: 'git',
  langchain: 'langchain', pandas: 'pandas', numpy: 'numpy', tailwind: 'tailwind',
  html: 'html5?', css: 'css3?', 'rest api': 'rest(?:ful)? api', databricks: 'databricks',
};
const clean = value => String(value ?? '').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
  .replace(/<[^>]*>/g, ' ').replace(/&nbsp;|&#160;/g, ' ').replace(/&amp;/g, '&')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"')
  .replace(/\s+/g, ' ').trim();
function skillsFrom(text) {
  return Object.entries(dictionary).filter(([,pattern]) => new RegExp('(?:^|[^a-z0-9])(?:' + pattern + ')(?=$|[^a-z0-9])', 'i').test(text)).map(([key]) => key);
}
function classify(title) {
  if (/data engineer|analytics engineer|data platform|etl|data architect/i.test(title)) return 'Data Engineer';
  if (/machine learning|\bml\b|\bai\b|artificial intelligence|data scientist/i.test(title)) return 'AI/ML Engineer';
  if (/devops|sre\b|site reliability|cloud|infrastructure|platform engineer/i.test(title)) return 'DevOps/Cloud';
  if (/full[ -]?stack/i.test(title)) return 'Fullstack Engineer';
  if (/front[ -]?end|\breact\b|\bvue\b|\bui engineer/i.test(title)) return 'Frontend Engineer';
  if (/back[ -]?end|\bapi\b|python|java\b|node\.?js|php|software engineer/i.test(title)) return 'Backend Engineer';
  return 'Other';
}
function seniority(title) {
  if (/lead|principal|staff|head of|architect/i.test(title)) return 'Lead/Principal';
  if (/senior|\bsr\.?\b/i.test(title)) return 'Senior';
  if (/junior|\bjr\.?\b|intern|entry[ -]level|graduate/i.test(title)) return 'Intern/Junior';
  return 'Mid-Level';
}
function parseSalary(raw, rates = {}) {
  const text = clean(raw).toUpperCase();
  const empty = { salary_min: null, salary_max: null, salary_currency: null, salary_annual_usd: null };
  if (!text || /COMPETITIVE|UNDISCLOSED|NEGOTIABLE/.test(text)) return empty;
  const currency = /\b(USD|EUR|GBP|CAD|AUD|PHP|INR|SGD)\b/.exec(text)?.[1]
    ?? (/\bCA?\$/.test(text) ? 'CAD' : /\bAU?\$/.test(text) ? 'AUD' : /\bSG?\$/.test(text) ? 'SGD' : text.includes('€') ? 'EUR' : text.includes('£') ? 'GBP' : /US\$|\$/.test(text) ? 'USD' : null);
  if (!currency) return empty;
  const matches = [...text.matchAll(/\d[\d,]*(?:\.\d+)?\s*K?/g)];
  if (!matches.length || matches.length > 2) return empty;
  let values = matches.map(m => Number(m[0].replace(/[,K\s]/g, '')) * (/K/.test(m[0]) ? 1000 : 1));
  if (values.length === 2 && /K/.test(matches[1][0]) && !/K/.test(matches[0][0]) && values[0] < 1000) values[0] *= 1000;
  const lo = Math.min(...values), hi = Math.max(...values);
  const factor = /HOUR|\/HR|\/H\b/.test(text) ? 2080 : /MONTH|\/MO\b/.test(text) ? 12 : /WEEK|\/WK\b/.test(text) ? 52 : /DAY|\/D\b/.test(text) ? 260 : 1;
  if (lo <= 0 || hi > 10000000 || (factor === 1 && hi < 1000 && !/YEAR|ANNUAL|\/YR/.test(text))) return empty;
  const rate = currency === 'USD' ? 1 : Number(rates[currency]);
  const annual = rate > 0 ? Math.round(((lo + hi) / 2) * factor * rate * 100) / 100 : null;
  return { salary_min: lo, salary_max: hi, salary_currency: currency, salary_annual_usd: annual && annual < 10000000000 ? annual : null };
}
function normalize(job, source, rates) {
  const title = clean(job.title), company = clean(job.company_name), url = job.url;
  const timestamp = String(job.publication_date ?? '');
  const utcTimestamp = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp) ? timestamp : timestamp + 'Z';
  const date = source === 'arbeitnow' ? new Date(Number(job.created_at) * 1000) : new Date(utcTimestamp);
  if (!title || !company || !(job.id ?? job.slug) || !/^https?:\/\//i.test(url ?? '') || !Number.isFinite(date.getTime()) || date > new Date()) return null;
  const description = clean(job.description), location = clean(job.candidate_required_location ?? job.location);
  const context = [title, description, ...(job.tags ?? [])].join(' ');
  const arrangement = source === 'remotive' || job.remote === true ? 'Remote' : /hybrid/i.test(location + ' ' + title) ? 'Hybrid' : job.remote === false ? 'On-site' : 'Unspecified';
  const countryMap = { 'united states': 'US', usa: 'US', germany: 'DE', 'united kingdom': 'GB', uk: 'GB', canada: 'CA', australia: 'AU', philippines: 'PH', singapore: 'SG', netherlands: 'NL' };
  const country = countryMap[location.toLowerCase()] ?? countryMap[location.split(',').at(-1).trim().toLowerCase()] ?? null;
  return {
    external_id: String(job.id ?? job.slug),
    fingerprint: createHash('sha256').update(company.toLowerCase() + '::' + title.toLowerCase() + '::' + source).digest('hex'),
    title, normalized_role: classify(title), company_name: company,
    company_logo_url: /^https?:\/\//i.test(job.company_logo ?? '') ? job.company_logo : null,
    location_raw: location || null, country, work_arrangement: arrangement,
    employment_type: clean(job.job_type || (job.job_types ?? []).join(', ')) || 'Unspecified',
    seniority_level: seniority(title), ...parseSalary(job.salary, rates),
    skills: skillsFrom(context), description_snippet: description.slice(0, 700), job_url: url,
    source, posted_at: date.toISOString(), scraped_at: new Date().toISOString(), is_active: true,
  };
}
const rates = JSON.parse($env.FX_USD_RATES || '{}');
const jobs = new Map(), errors = [];
let found = 0, rejected = 0;
for (const [nodeName, source, field] of [['Fetch Remotive', 'remotive', 'jobs'], ['Fetch Arbeitnow', 'arbeitnow', 'data']]) {
  const response = $(nodeName).first().json;
  const body = response.body ?? response;
  if (response.error || response.statusCode >= 400 || !Array.isArray(body[field])) {
    errors.push(source + ': feed request failed or returned an invalid payload');
    continue;
  }
  for (const raw of body[field]) {
    found++;
    const job = normalize(raw, source, rates);
    if (job) jobs.set(job.fingerprint, job); else rejected++;
  }
}
return [{ json: { jobs: [...jobs.values()], jobs_found: found, rejected, errors } }];
