(() => {
  'use strict';
  const charts = new Map();
  const palette = ['#34d399', '#818cf8', '#38bdf8', '#fbbf24', '#fb7185', '#c084fc', '#94a3b8'];
  const dollars = value => value == null ? 'Not disclosed' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const base = () => ({ responsive: true, maintainAspectRatio: false, animation: reduceMotion ? false : { duration: 300 }, plugins: { legend: { labels: { color: '#91a2ba', boxWidth: 8, boxHeight: 8, usePointStyle: true, font: { size: 10 } } }, tooltip: { backgroundColor: '#0b1120', borderColor: '#334155', borderWidth: 1, padding: 12 } }, scales: { x: { grid: { color: '#24304760' }, border: { display: false }, ticks: { color: '#8b9bb3', font: { size: 10 }, maxRotation: 0 } }, y: { beginAtZero: true, grid: { color: '#24304760' }, border: { display: false }, ticks: { color: '#8b9bb3', font: { size: 10 }, precision: 0 } } } });
  function draw(id, type, data, options, empty) {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    if (charts.has(id)) charts.get(id).destroy();
    charts.set(id, new Chart(canvas, { type, data, options }));
    canvas.closest('article').querySelector('.chart-empty')?.classList.toggle('hidden', !empty);
  }
  function render() {
    const carrier = document.getElementById('chart-data');
    if (!carrier) return;
    if (!window.Chart) {
      document.querySelectorAll('.chart-empty').forEach(element => {
        element.textContent = 'Charts could not load. Check your connection and reload this page.';
        element.classList.remove('hidden');
      });
      return;
    }
    const { trends, days } = JSON.parse(carrier.textContent);
    const labels = [];
    const now = new Date();
    for (let offset = days; offset >= 0; offset--) {
      const date = new Date(now);
      date.setUTCDate(date.getUTCDate() - offset);
      labels.push(date.toISOString().slice(0, 10));
    }
    const roles = [...new Set(trends.daily_volume.map(row => row.normalized_role))].sort();
    const lookup = new Map(trends.daily_volume.map(row => [row.post_date + '|' + row.normalized_role, row.job_count]));
    const velocity = base();
    velocity.plugins.legend.position = 'bottom';
    velocity.scales.x.ticks.maxTicksLimit = 7;
    velocity.scales.x.ticks.callback = function (value) { return labels[value]?.slice(5).replace('-', '/'); };
    draw('velocity-chart', 'line', { labels, datasets: roles.map((role, i) => ({ label: role, data: labels.map(day => lookup.get(day + '|' + role) || 0), borderColor: palette[i % palette.length], backgroundColor: palette[i % palette.length] + '10', fill: true, borderWidth: 2, pointRadius: 0, pointHitRadius: 12, tension: 0.3 })) }, velocity, !roles.length);
    const skills = trends.top_skills.slice(0, 15), skillOptions = base();
    skillOptions.indexAxis = 'y';
    skillOptions.plugins.legend.display = false;
    skillOptions.scales.x.ticks.precision = 0;
    skillOptions.plugins.tooltip.callbacks = { afterLabel: item => 'Avg. annual pay: ' + dollars(skills[item.dataIndex].avg_salary_usd) };
    draw('skills-chart', 'bar', { labels: skills.map(row => row.skill), datasets: [{ label: 'Openings', data: skills.map(row => row.mention_count), backgroundColor: skills.map((_, i) => i < 3 ? '#34d399' : '#818cf890'), borderRadius: 3, maxBarThickness: 14 }] }, skillOptions, !skills.length);
    const salary = trends.salary_benchmarks, salaryOptions = base();
    salaryOptions.indexAxis = 'y';
    salaryOptions.plugins.legend.position = 'bottom';
    salaryOptions.scales.x.ticks.callback = value => '$' + Math.round(value / 1000) + 'k';
    salaryOptions.scales.y.ticks.autoSkip = false;
    salaryOptions.scales.y.ticks.font.size = 8;
    salaryOptions.plugins.tooltip.callbacks = { label: item => item.dataset.label + ': ' + dollars(item.raw), afterBody: items => salary[items[0].dataIndex].job_count + ' disclosed salaries' };
    draw('salary-chart', 'bar', { labels: salary.map(row => [row.normalized_role.replace(' Engineer', '').replace('Fullstack', 'Fullstack'), row.seniority_level || 'Unspecified']), datasets: [['Min', 'min_salary', '#475569'], ['Median', 'median_salary', '#818cf8'], ['Max', 'max_salary', '#34d399']].map(([label, key, color]) => ({ label, data: salary.map(row => row[key]), backgroundColor: color, borderRadius: 2, maxBarThickness: 8 })) }, salaryOptions, !salary.length);
    const split = trends.work_arrangements, arrangementOptions = base();
    delete arrangementOptions.scales;
    arrangementOptions.cutout = '74%';
    arrangementOptions.plugins.legend.position = 'right';
    arrangementOptions.plugins.tooltip.callbacks = { label: item => `${item.label}: ${item.raw} (${split[item.dataIndex].percentage}%)` };
    draw('arrangement-chart', 'doughnut', { labels: split.map(row => row.work_arrangement), datasets: [{ data: split.map(row => row.job_count), backgroundColor: [ '#818cf8', '#fbbf24', '#34d399', '#64748b' ], borderWidth: 0, hoverOffset: reduceMotion ? 0 : 4 }] }, arrangementOptions, false);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render, { once: true });
  else render();
  document.addEventListener('htmx:beforeSwap', event => {
    const target = event.detail.target;
    for (const [id, chart] of charts) {
      const canvas = document.getElementById(id);
      if (canvas && target.contains(canvas) && event.detail.xhr.status < 400) { chart.destroy(); charts.delete(id); }
    }
    if (event.detail.xhr.status >= 400 && target.id === 'scrape-feedback') {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });
  document.addEventListener('htmx:afterSettle', event => {
    if (event.detail.target.id === 'dashboard-content' || event.detail.target.id === 'charts-section') render();
  });
  document.addEventListener('htmx:configRequest', event => {
    if (event.detail.path === '/api/v1/scrape/trigger') {
      const token = document.getElementById('scrape-token')?.value;
      if (token) event.detail.headers['X-Scrape-Token'] = token;
    }
    document.getElementById('request-error')?.classList.add('hidden');
  });
  function showError(message) {
    const box = document.getElementById('request-error');
    if (box) { box.textContent = message; box.classList.remove('hidden'); }
  }
  document.addEventListener('htmx:responseError', () => showError('Could not refresh this view. Your previous results are still shown. Try again shortly.'));
  document.addEventListener('htmx:sendError', () => showError('Connection interrupted. Check your network and try again.'));
})();
