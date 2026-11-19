// SPDX-License-Identifier: CDDL-1.1
import { h, render } from 'preact';
import { Start } from './start';

for (const root of document.querySelectorAll<HTMLElement>('[data-entra-owner-start]:not([data-mounted])')) {
    const definitionId = root.dataset.definitionId;
    const mount = root.querySelector('[data-mount]');
    if (!definitionId || !mount) continue;
    root.dataset.mounted = 'true';
    const host = root.closest('form');
    const defaultStart = host?.querySelector<HTMLInputElement>('input[name="startProcessButton"]');
    if (defaultStart) defaultStart.disabled = true;
    host?.addEventListener('submit', event => event.preventDefault());
    mount.replaceChildren();
    render(<Start definitionId={definitionId} />, mount);
}
