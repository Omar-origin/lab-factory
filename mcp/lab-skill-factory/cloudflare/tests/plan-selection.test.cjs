const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

async function load(url) {
  const nodes = new Map();
  function element(id) {
    if (!nodes.has(id)) nodes.set(id, {
      checked: false, disabled: false, textContent: '', innerHTML: '', dataset: {}, listeners: {},
      classList: { toggle() {} },
      addEventListener(name, handler) { this.listeners[name] = handler; },
    });
    return nodes.get(id);
  }
  const cards = ['experience', 'permanent', 'team'].map(id => Object.assign(element(id), { dataset: { plan: id } }));
  const location = { href: url };
  const context = vm.createContext({
    URL, encodeURIComponent, location,
    history: { replaceState(_state, _title, value) { location.href = String(value); } },
    document: { querySelector: element, querySelectorAll: () => cards },
    navigator: { clipboard: { writeText: async () => {} } },
    Lab: {
      escape: value => value, money: value => String(value), toast: () => {},
      mountShell: async () => null,
      request: async () => ({ plans: cards.map((card, i) => ({ id: card.dataset.plan, name: card.dataset.plan, amount_cents: [990, 4990, 19900][i] })) }),
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../public/plans/plans.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  return { nodes, cards, location };
}
(async () => {
  const restored = await load('https://local.test/plans?plan=team&credit=1');
  assert.equal(restored.nodes.get('#selectedName').textContent, 'team');
  assert.equal(restored.nodes.get('#useCredit').checked, true);
  const changed = await load('https://local.test/plans?plan=invalid');
  assert.equal(changed.nodes.get('#selectedName').textContent, 'experience');
  changed.cards[2].listeners.click();
  changed.nodes.get('#useCredit').checked = true;
  await changed.nodes.get('#createOrder').listeners.click();
  const next = new URL(changed.location.href, 'https://local.test').searchParams.get('next');
  assert.equal(next, '/plans?plan=team&credit=1');
  assert.equal(changed.nodes.get('#continueCheckout').textContent, 'team · 查看账单');
  console.log('PASS: selected plan, invalid parameter fallback, login return, credit preference, mobile summary');
})().catch(error => { console.error(error); process.exitCode = 1; });
