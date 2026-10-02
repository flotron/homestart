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

test('physical drives select one most-specific volume, including nested and duplicate mounts', () => {
  const root = {mountpoints: [{allowed: true, path: '/'}]};
  const boot = {mountpoints: [{allowed: true, path: '/boot'}]};
  const duplicate = {mountpoints: [{allowed: true, path: '/boot'}]};
  const hidden = {mountpoints: [{allowed: false, path: '/boot/private'}]};
  const state = {filePath: '/boot/private/file', fileDriveEntries: [{children: [root, boot, duplicate, hidden]}]};
  const context = vm.createContext({state});
  vm.runInContext(appSource.slice(appSource.indexOf('function activeDriveEntry'), appSource.indexOf('function renderDriveEntry')), context);
  vm.runInContext(appSource.slice(appSource.indexOf('function rootContainsPath'), appSource.indexOf('function setFileLocationsOpen')), context);
  assert.equal(context.activeDriveEntry(), boot);
  state.filePath = '/bootleg';
  assert.equal(context.activeDriveEntry(), root);
  state.filePath = '/';
  assert.equal(context.activeDriveEntry(), root);
  state.filePath = '';
  assert.equal(context.activeDriveEntry(), null);
});

test('folder navigation ignores stale successes and stale errors after a newer click', async () => {
  for (const staleError of [false, true]) {
    const pending = [];
    const state = {selectedFiles: new Set()};
    let renders = 0;
    const context = vm.createContext({state, encodeURIComponent,
      fetch: () => new Promise(resolve => pending.push(resolve)),
      window: {alert() { assert.fail('stale errors must not interrupt the new folder'); }},
      filePathNode: {}, fileLocationName: {}, fileCount: {}, fileUp: {}, sambaUseCurrent: {},
      currentFolderName: path => path, updateFileControls() {}, renderRoots() { renders++; }, renderSortedFiles() {},
    });
    vm.runInContext(appSource.slice(appSource.indexOf('let fileNavigationRequest'), appSource.indexOf('function sambaAccessLabel')), context);
    const first = context.loadFiles('/old');
    const last = context.loadFiles('/new');
    pending[1]({ok: true, json: async () => ({path: '/new'})});
    await last;
    pending[0]({ok: !staleError, json: async () => staleError ? {error: 'old failure'} : {path: '/old'}});
    await first;
    assert.equal(state.filePath, '/new');
    assert.equal(renders, 1);
  }
});

test('drive headings expand without opening files; volume rows provide one Open action', async () => {
  class Node {
    constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.parts = {}; this.style = {setProperty() {}}; this.classList = {add() {}}; }
    set innerHTML(value) {
      for (const selector of ['.drive-icon', 'strong', 'small', '.drive-status']) this.parts[selector] = new Node('span');
    }
    appendChild(child) { this.children.push(child); return child; }
    append(...children) { this.children.push(...children); }
    querySelector(selector) { return this.parts[selector] || this.children.find(c => `.${c.className}` === selector); }
    setAttribute(key, value) { this.attrs[key] = value; }
    addEventListener(key, fn) { this.listeners[key] = fn; }
  }
  const opened = [], mounted = [];
  const state = {features: {file_operations: true}, filePath: '/boot'};
  const context = vm.createContext({state, document: {createElement: tag => new Node(tag)},
    openFileLocation: path => opened.push(path), mountDriveEntry: async entry => mounted.push(entry.path), console});
  vm.runInContext(appSource.slice(appSource.indexOf('const driveExpansion'), appSource.indexOf('function rootContainsPath')), context);
  const volume = {path: '/dev/sdb1', name: 'sdb1', mountpoints: [{allowed: true, path: '/boot'}]};
  const disk = {path: '/dev/sdb', children: [volume]};
  const tree = context.renderDriveEntry(disk, volume);
  const toggle = tree.children[0].querySelector('.drive-target');
  assert.equal(toggle.tag, 'button');
  assert.equal(tree.children[1].hidden, true);
  toggle.listeners.click();
  assert.equal(tree.children[1].hidden, false);
  assert.equal(toggle.attrs['aria-expanded'], 'true');
  assert.equal(opened.length, 0);
  assert.equal(context.renderDriveEntry(disk, volume).children[1].hidden, false);
  const browse = tree.children[1].children[0].querySelector('.drive-target');
  browse.listeners.click();
  assert.deepEqual(opened, ['/boot']);
  const available = context.renderDriveNode({path: '/dev/sdc1', can_mount: true}, false, null);
  const target = available.querySelector('.drive-target');
  assert.equal(target.querySelector('.drive-open-label').textContent, 'Open');
  const first = target.listeners.click();
  await target.listeners.click();
  await first;
  assert.deepEqual(mounted, ['/dev/sdc1']);
  assert.equal(target.disabled, false);
  state.features.file_mounts = false;
  assert.equal(context.renderDriveNode({can_mount: true}, false, null).querySelector('.drive-target').tag, 'div');
});
