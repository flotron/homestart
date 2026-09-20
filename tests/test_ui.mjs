import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const appSource = fs.readFileSync(new URL('../static/app.js', import.meta.url), 'utf8');
const powerSource = fs.readFileSync(new URL('../static/power.js', import.meta.url), 'utf8');

function powerHarness({available = true, reject = false} = {}) {
  const nodes = new Map();
  function node(key) {
    if (!nodes.has(key)) nodes.set(key, {
      listeners: {}, disabled: false, hidden: false, checked: false, textContent: '', dataset: {},
      label: {hidden: false},
      addEventListener(name, callback) { this.listeners[name] = callback; },
      closest() { return this.label; }, focus() {},
      showModal() { this.open = true; }, close() { this.open = false; },
    });
    return nodes.get(key);
  }
  const buttons = [node('reboot'), node('poweroff')];
  buttons.forEach(button => { button.dataset.hostPower = button === buttons[0] ? 'reboot' : 'poweroff'; });
  const requests = [];
  const ctx = {document: {querySelector: node, querySelectorAll: () => buttons},
    window: {}, AbortSignal, Date, Error, JSON, Boolean,
    fetch: async (url, options = {}) => {
      requests.push({url, options});
      if (options.method === 'POST') {
        if (reject) throw new Error('Lost reply');
        return {ok: true, json: async () => ({ok: true, accepted: true, available, hostname: 'host-a', pending: {action: 'poweroff'}})};
      }
      return {ok: true, json: async () => ({ok: true, available, hostname: 'host-a', pending: null, boot_id: 'boot-a', reason: available ? '' : 'Unavailable'})};
    }};
  vm.runInNewContext(powerSource, ctx);
  const emit = (key, event) => node(key).listeners[event]({preventDefault() {}});
  return {node, requests, ctx, emit};
}

test('power dialog: opening/cancelling sends no power command; confirming sends exactly one', async () => {
  const h = powerHarness();
  await h.emit('poweroff', 'click');
  assert.equal(h.node('#power-dialog').open, true);
  assert.equal(h.node('#power-submit').disabled, true);
  assert.match(h.node('#power-title').textContent, /host-a/);
  await h.emit('#power-form', 'submit');
  h.emit('#power-cancel', 'click');
  assert.equal(h.requests.filter(r => r.options.method === 'POST').length, 0);
  await h.emit('poweroff', 'click');
  h.node('#power-confirmation').checked = true;
  h.emit('#power-confirmation', 'change');
  assert.equal(h.node('#power-submit').disabled, false);
  await Promise.all([h.emit('#power-form', 'submit'), h.emit('#power-form', 'submit')]);
  const posts = h.requests.filter(r => r.options.method === 'POST');
  assert.equal(posts.length, 1);
  assert.deepEqual(JSON.parse(posts[0].options.body), {action:'poweroff',confirmation:'poweroff',hostname:'host-a'});
  assert.equal(h.ctx.window.HomeStartPower.pending, true);
  assert.match(h.node('#power-progress').textContent, /Shutdown accepted/);
});

test('lost power reply is not automatically retried or shown as success', async () => {
  const h = powerHarness({reject: true});
  await h.emit('poweroff', 'click');
  h.node('#power-confirmation').checked = true;
  await h.emit('#power-form', 'submit');
  assert.equal(h.requests.filter(r => r.options.method === 'POST').length, 1);
  assert.match(h.node('#power-progress').textContent, /Check the computer state/);
  assert.equal(h.node('#power-submit').hidden, true);
});

test('unsupported host keeps power buttons unavailable', async () => {
  const h = powerHarness({available: false});
  await h.ctx.window.HomeStartPower.refresh();
  assert.equal(h.node('poweroff').disabled, true);
  await h.emit('poweroff', 'click');
  assert.notEqual(h.node('#power-dialog').open, true);
  assert.equal(h.requests.filter(r => r.options.method === 'POST').length, 0);
});

test('metrics skip hidden views and deduplicate slow requests; errors release the lock', async () => {
  const context = vm.createContext({state: {view:'status'}, document:{hidden:false}, window:{}});
  vm.runInContext(appSource.slice(appSource.indexOf('const overviewRequests'), appSource.indexOf('const navItems')), context);
  const run = context.visibleOverviewRequest;
  let calls = 0, finish;
  const slow = () => { calls++; return new Promise(resolve => {finish=resolve;}); };
  const first = run('system', slow);
  await run('system', slow);
  assert.equal(calls, 1);
  finish(); await first;
  context.state.view = 'apps'; await run('system', slow);
  context.state.view = 'status'; context.document.hidden = true; await run('system', slow);
  context.document.hidden = false; context.window.HomeStartPower = {pending: true}; await run('system', slow);
  assert.equal(calls, 1);
  context.window.HomeStartPower.pending = false;
  await assert.rejects(run('system', async () => {throw new Error('offline');}));
  await run('system', async () => {calls++;});
  assert.equal(calls, 2);
});

test('malformed favorites do not prevent application startup', () => {
  for (const stored of ['{bad json', '{}', 'null', '[]']) {
    const context = vm.createContext({localStorage: {getItem: () => stored},sessionStorage: {getItem: () => null}});
    vm.runInContext(appSource.slice(0, appSource.indexOf('const overviewRequests')), context);
    assert.equal(vm.runInContext('state.favorites.size', context), 0);
  }
});
