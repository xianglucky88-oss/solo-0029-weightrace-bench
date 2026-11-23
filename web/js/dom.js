export const $ = (id) => document.getElementById(id);

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (typeof value === 'boolean') node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

export function button(label, action, cls = 'quiet', options = {}) {
  return el('button', { type: 'button', class: cls, onclick: action, ...options }, label);
}

export function table(headers, rows, empty = '暂无记录') {
  if (!rows.length) return el('p', { class: 'placeholder' }, empty);
  return el('table', {}, el('thead', {}, el('tr', {}, headers.map((text) => el('th', { scope: 'col' }, text)))),
    el('tbody', {}, rows.map((row) => el('tr', {}, row.map((cell) => el('td', {}, cell))))));
}

export function labelled(label, control) {
  return el('label', {}, label, control);
}
