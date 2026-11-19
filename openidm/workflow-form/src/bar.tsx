// SPDX-License-Identifier: CDDL-1.1
import { h, render } from 'preact';
import { Review } from './review';

for (const root of document.querySelectorAll<HTMLElement>('[data-entra-owner-form]:not([data-mounted])')) {
    root.dataset.mounted = 'true';
    const data = Object.fromEntries([...root.querySelectorAll<HTMLTextAreaElement>('textarea[data-field]')].map(field => [field.dataset.field, field.value]));
    const mount = root.querySelector('[data-mount]');
    if (!mount) continue;
    mount.replaceChildren();
    render(<Review data={data} />, mount);
}
