/* Host controls: explicit confirmation and a single non-retried POST. */
(() => {
  const dialog = document.querySelector('#power-dialog');
  const form = document.querySelector('#power-form');
  const title = document.querySelector('#power-title');
  const description = document.querySelector('#power-description');
  const confirmation = document.querySelector('#power-confirmation');
  const submit = document.querySelector('#power-submit');
  const cancel = document.querySelector('#power-cancel');
  const progress = document.querySelector('#power-progress');
  const availability = document.querySelector('#power-availability');
  const host = document.querySelector('#power-host');
  const buttons = [...document.querySelectorAll('[data-host-power]')];
  let status = null;
  let action = null;
  let sending = false;
  let accepted = false;
  let watchGeneration = 0;

  async function readStatus() {
    const response = await fetch('/api/system/power', {
      cache: 'no-store', signal: AbortSignal.timeout(12000),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not check host power controls');
    return data;
  }

  function displayStatus(data) {
    status = data;
    host.textContent = data.hostname;
    buttons.forEach(button => { button.disabled = !data.available || Boolean(data.pending) || sending; });
    availability.textContent = data.pending
      ? `A ${data.pending.action === 'reboot' ? 'restart' : 'shutdown'} request was accepted for this computer.`
      : data.reason || 'You will confirm the computer name before continuing.';
  }

  async function refresh() {
    try { displayStatus(await readStatus()); }
    catch (error) {
      buttons.forEach(button => { button.disabled = true; });
      availability.textContent = error.message;
    }
  }

  async function open(actionName) {
    if (sending || accepted) return;
    buttons.forEach(button => { button.disabled = true; });
    await refresh();
    if (!status?.available || status.pending || buttons.every(button => button.disabled)) return;
    action = actionName;
    confirmation.checked = false;
    confirmation.disabled = false;
    confirmation.closest('label').hidden = false;
    submit.hidden = false;
    submit.disabled = true;
    cancel.textContent = 'Cancel';
    progress.textContent = '';
    title.textContent = `${action === 'reboot' ? 'Restart' : 'Shut down'} ${status.hostname}?`;
    description.textContent = action === 'reboot'
      ? 'This restarts the entire Linux computer, including HomeStart and all its services. HomeStart will check when the computer returns.'
      : 'This shuts down the entire Linux computer. You will need to turn it on again using its power button or another method already configured.';
    submit.textContent = action === 'reboot' ? 'Restart computer' : 'Shut down computer';
    dialog.showModal();
    cancel.focus();
  }

  async function watchRestart(bootId) {
    const generation = ++watchGeneration;
    const deadline = Date.now() + 180000;
    while (generation === watchGeneration && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 3000));
      if (generation !== watchGeneration) return;
      try {
        const data = await readStatus();
        if (bootId && data.boot_id && data.boot_id !== bootId) {
          progress.textContent = 'Computer restarted. Reconnecting…';
          window.location.reload();
          return;
        }
        if (!data.pending && !data.available) break;
        progress.textContent = 'Restart requested. Waiting for the computer to restart…';
      } catch {
        progress.textContent = 'Connection interrupted. Waiting for HomeStart to return…';
      }
    }
    if (generation === watchGeneration) {
      progress.textContent = 'Restart could not be confirmed yet. Check the computer or reload HomeStart. The command will not be sent again automatically.';
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (sending || accepted || !confirmation.checked || !status || !action) return;
    sending = true;
    submit.disabled = true;
    cancel.disabled = true;
    confirmation.disabled = true;
    progress.textContent = 'Sending request to the computer…';
    const bootId = status.boot_id;
    try {
      const response = await fetch('/api/system/power', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, confirmation: action, hostname: status.hostname }),
        signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      if (!response.ok || !data.accepted) {
        throw new Error(data.error || 'The power request was not accepted');
      }
      accepted = true;
      displayStatus(data);
      submit.hidden = true;
      confirmation.closest('label').hidden = true;
      cancel.textContent = 'Close';
      progress.textContent = action === 'reboot'
        ? 'Restart accepted. Waiting for the computer to restart…'
        : 'Shutdown accepted. The computer will begin shutting down in about 5 seconds. HomeStart will become unavailable.';
      if (action === 'reboot') watchRestart(bootId);
    } catch (error) {
      // A lost reply does not prove that systemd rejected the request. Never retry it.
      progress.textContent = `${error.message}. Check the computer state before sending another request.`;
      submit.hidden = true;
      cancel.textContent = 'Close';
      await refresh();
    } finally {
      sending = false;
      cancel.disabled = false;
    }
  });
  confirmation.addEventListener('change', () => { submit.disabled = !confirmation.checked || sending; });
  cancel.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (sending) event.preventDefault(); });
  buttons.forEach(button => button.addEventListener('click', () => open(button.dataset.hostPower)));
  window.HomeStartPower = { refresh, get pending() { return sending || accepted || Boolean(status?.pending); } };
})();
