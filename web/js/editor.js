import { $, button, el } from './dom.js';

export function openEditor(title, ...content) {
  $('dialog-title').textContent = title;
  $('dialog-content').replaceChildren(...content);
  if (!$('editor').open) $('editor').showModal();
}

export function closeEditor() {
  $('editor').close();
}

export function editorForm(fields, submitLabel, submit) {
  const error = el('p', { class: 'dialog-error', role: 'alert' });
  const save = el('button', { type: 'submit', class: 'primary' }, submitLabel);
  return el('form', { onsubmit: async (event) => {
    event.preventDefault();
    error.textContent = '';
    save.disabled = true;
    try { await submit(new FormData(event.currentTarget)); }
    catch (failure) { error.textContent = failure.message || '操作未完成'; }
    finally { save.disabled = false; }
  } }, fields, error, el('div', { class: 'dialog-actions' }, button('取消', closeEditor), save));
}
